"""Liga as regras de alerta ao banco e ao e-mail: avalia cada coleta válida e registra o que foi enviado."""
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.status import StatusColeta
from ..db.models import Alerta, Coleta, Produto
from .config import regra_do_produto
from .email import (
    ConfigSMTP,
    carregar_config_smtp,
    construir_alerta,
    construir_resumo,
    construir_teste,
    enviar_smtp,
)
from .regras import Decisao, UltimoAlerta, avaliar

log = logging.getLogger("searching.alertas")

_COLUNA_PRECO = {"pix": Coleta.preco_pix_centavos, "cartao_1x": Coleta.preco_cartao_1x_centavos}
_ATRIBUTO_PRECO = {"pix": "preco_pix_centavos", "cartao_1x": "preco_cartao_1x_centavos"}


@dataclass
class Notificador:
    """Agrupa como carregar a configuração SMTP e como enviar; trocável nos testes."""

    carregar_config: Callable[[], ConfigSMTP] = field(default=carregar_config_smtp)
    enviar: Callable = field(default=enviar_smtp)


def _precos_anteriores(s: Session, produto_id: int, base: str, antes_de: datetime) -> list[tuple[datetime, int]]:
    coluna = _COLUNA_PRECO[base]
    linhas = s.execute(
        select(Coleta.coletado_em, coluna).where(
            Coleta.produto_id == produto_id,
            Coleta.status == StatusColeta.OK.value,
            coluna.is_not(None),
            Coleta.coletado_em < antes_de,
        )
    ).all()
    return [(quando, preco) for quando, preco in linhas]


def _ultimo_alerta(s: Session, produto_id: int) -> UltimoAlerta | None:
    a = s.scalars(
        select(Alerta).where(Alerta.produto_id == produto_id, Alerta.sucesso.is_(True)).order_by(Alerta.id.desc()).limit(1)
    ).first()
    if a is None:
        return None
    # A referência temporal é a coleta que gerou o alerta (o e-mail pode ter saído depois dela).
    coleta = s.get(Coleta, a.coleta_id) if a.coleta_id else None
    return UltimoAlerta(a.preco_atual_centavos, coleta.coletado_em if coleta else a.enviado_em)


def processar_coleta(s: Session, produto: Produto, coleta: Coleta, cfg: dict, notificador: Notificador) -> Alerta | None:
    """Avalia a coleta e, se couber, envia o e-mail e registra o alerta. Nunca lança por falha de envio."""
    if cfg.get("alertas_ativos") != "1":
        return None
    if coleta.status != StatusColeta.OK.value:  # RF-25: nada de alerta sobre coleta suspeita ou com falha
        return None

    base = cfg["alerta_base_preco"]
    atual = getattr(coleta, _ATRIBUTO_PRECO[base])
    if atual is None:
        return None

    regra = regra_do_produto(produto, cfg)
    decisao = avaliar(
        regra, atual, coleta.coletado_em, _precos_anteriores(s, produto.id, base, coleta.coletado_em), _ultimo_alerta(s, produto.id)
    )
    if decisao is None:
        return None

    alerta = Alerta(
        produto_id=produto.id,
        coleta_id=coleta.id,
        preco_anterior_centavos=decisao.preco_anterior_centavos,
        preco_atual_centavos=decisao.preco_atual_centavos,
        queda_pct=decisao.queda_pct,
        base_preco=base,
        motivos=",".join(decisao.motivos),
        enviado_em=datetime.now(),
        sucesso=False,
    )
    try:
        smtp = notificador.carregar_config()
        alerta.destinatario = ", ".join(smtp.destinatarios)
        notificador.enviar(construir_alerta(produto, coleta, decisao, base, smtp.remetente, smtp.destinatarios), smtp)
        alerta.sucesso = True
    except Exception as exc:
        alerta.erro = f"{type(exc).__name__}: {exc}"
        log.warning("alerta de %s não enviado: %s", produto.nome_comercial, alerta.erro)
    s.add(alerta)
    s.commit()
    return alerta


def reenviar_pendentes(s: Session, notificador: Notificador, dias: int = 3) -> int:
    """Tenta de novo os alertas que falharam nos últimos dias (ex.: senha de app corrigida depois)."""
    desde = datetime.now() - timedelta(days=dias)
    pendentes = s.scalars(select(Alerta).where(Alerta.sucesso.is_(False), Alerta.enviado_em >= desde).order_by(Alerta.id)).all()
    reenviados = 0
    for a in pendentes:
        produto, coleta = s.get(Produto, a.produto_id), (s.get(Coleta, a.coleta_id) if a.coleta_id else None)
        if produto is None or coleta is None:
            continue
        decisao = Decisao(a.preco_anterior_centavos, a.preco_atual_centavos, a.queda_pct, tuple((a.motivos or "queda").split(",")))
        try:
            smtp = notificador.carregar_config()
            notificador.enviar(construir_alerta(produto, coleta, decisao, a.base_preco or "pix", smtp.remetente, smtp.destinatarios), smtp)
            a.sucesso, a.erro, a.enviado_em, a.destinatario = True, None, datetime.now(), ", ".join(smtp.destinatarios)
            reenviados += 1
        except Exception as exc:
            a.erro = f"{type(exc).__name__}: {exc}"
    s.commit()
    return reenviados


def enviar_resumo(resumo: dict, notificador: Notificador, quando: datetime | None = None) -> tuple[bool, str]:
    """Resumo diário (RF-27). Devolve (enviado, mensagem)."""
    try:
        smtp = notificador.carregar_config()
        notificador.enviar(construir_resumo(resumo, quando or datetime.now(), smtp.remetente, smtp.destinatarios), smtp)
        return True, "Resumo enviado."
    except Exception as exc:
        log.warning("resumo diário não enviado: %s", exc)
        return False, f"{type(exc).__name__}: {exc}"


def enviar_teste(notificador: Notificador | None = None) -> tuple[bool, str]:
    """E-mail de teste (RF-28): confirma credenciais e destinatários sem depender de uma queda real."""
    notificador = notificador or Notificador()
    try:
        smtp = notificador.carregar_config()
        notificador.enviar(construir_teste(smtp.remetente, smtp.destinatarios), smtp)
        return True, f"E-mail de teste enviado para {', '.join(smtp.destinatarios)}."
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"
