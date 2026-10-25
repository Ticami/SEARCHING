"""Resumo semanal em Excel por e-mail.

Quem recebe o quê: a lista de destinatários (interface/.env) recebe todos os produtos; cada usuário com assinaturas recebe
só os produtos que assinou. Roda por agendador (`python -m searching.operacao resumo-semanal`), no máximo uma vez por semana.
"""
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.precos import formatar_brl
from ..db.models import Assinatura, Coleta, Configuracao, Produto, Usuario
from ..relatorios import exportar_excel
from . import destinatarios as dest
from .email import construir_resumo_semanal
from .servico import Notificador

log = logging.getLogger("searching.alertas")
CHAVE_ULTIMO = "resumo_semanal_ultimo_envio"


@dataclass
class Variacao:
    produto: str
    loja: str
    primeiro: int | None
    ultimo: int | None
    minimo: int | None

    @property
    def pct(self) -> float | None:
        if self.primeiro and self.ultimo is not None:
            return round((self.ultimo - self.primeiro) / self.primeiro * 100, 1)
        return None


def _coletas_da_semana(s: Session, produto_ids: set[int] | None, desde: datetime):
    consulta = select(Coleta).where(Coleta.coletado_em >= desde).order_by(Coleta.coletado_em, Coleta.id)
    if produto_ids is not None:
        consulta = consulta.where(Coleta.produto_id.in_(produto_ids))
    return list(s.scalars(consulta))


def montar(s: Session, produto_ids: set[int] | None, agora: datetime, dias: int = 7) -> tuple[bytes, list[Variacao]] | None:
    """Excel das coletas dos últimos `dias` + variação de PIX por produto. None se não houve coleta."""
    coletas = _coletas_da_semana(s, produto_ids, agora - timedelta(days=dias))
    if not coletas:
        return None
    por_produto: dict[int, list[Coleta]] = {}
    for c in coletas:
        por_produto.setdefault(c.produto_id, []).append(c)
    variacoes = []
    for pid, lista in por_produto.items():
        p = s.get(Produto, pid)
        precos = [c.preco_pix_centavos for c in lista if c.status == "OK" and c.preco_pix_centavos is not None]
        variacoes.append(Variacao(p.nome_comercial, p.loja, precos[0] if precos else None, precos[-1] if precos else None, min(precos) if precos else None))
    variacoes.sort(key=lambda v: (v.pct is None, v.pct if v.pct is not None else 0))  # maiores quedas primeiro
    return exportar_excel(s, [c.id for c in coletas]), variacoes


def _linhas_texto(variacoes: list[Variacao]) -> str:
    out = []
    for v in variacoes:
        if v.ultimo is None:
            out.append(f"- {v.produto} ({v.loja}): sem preço válido na semana")
        else:
            pct = f"{v.pct:+.1f}%".replace(".", ",") if v.pct is not None else "—"
            out.append(f"- {v.produto} ({v.loja}): {formatar_brl(v.ultimo)} ({pct} na semana; mínimo {formatar_brl(v.minimo)})")
    return "\n".join(out)


def enviar(s: Session, notificador: Notificador, agora: datetime | None = None, dias: int = 7, forcar: bool = False,
           simular: bool = False) -> dict:
    """Devolve {'enviados': [emails], 'falhas': {email: erro}, 'pulado': motivo|None}."""
    agora = agora or datetime.now()
    resultado: dict = {"enviados": [], "falhas": {}, "pulado": None}
    if not forcar:
        ultimo = s.get(Configuracao, CHAVE_ULTIMO)
        if ultimo and agora - datetime.fromisoformat(ultimo.valor) < timedelta(days=6):
            resultado["pulado"] = f"já enviado em {ultimo.valor}"
            return resultado
    smtp = notificador.carregar_config()

    # destino -> conjunto de produtos (None = todos)
    destinos: dict[str, set[int] | None] = {e: None for e in dest.configurados(s) or smtp.destinatarios}
    por_usuario: dict[str, set[int]] = {}
    for a in s.scalars(select(Assinatura)):
        u = s.get(Usuario, a.usuario_id)
        if u and u.ativo:
            por_usuario.setdefault(u.email, set()).add(a.produto_id)
    for email, ids in por_usuario.items():
        if email not in destinos:  # quem já recebe tudo não recebe duas vezes
            destinos[email] = ids

    for email, ids in destinos.items():
        pacote = montar(s, ids, agora, dias)
        if pacote is None:
            continue
        excel, variacoes = pacote
        if simular:
            resultado["enviados"].append(email)
            continue
        try:
            msg = construir_resumo_semanal(smtp.remetente, [email], agora, dias, _linhas_texto(variacoes), excel)
            notificador.enviar(msg, smtp)
            resultado["enviados"].append(email)
        except Exception as exc:
            resultado["falhas"][email] = f"{type(exc).__name__}: {exc}"
            log.warning("resumo semanal para %s não enviado: %s", email, exc)
    if not simular and resultado["enviados"]:
        s.merge(Configuracao(chave=CHAVE_ULTIMO, valor=agora.isoformat(timespec="seconds")))
        s.commit()
    return resultado
