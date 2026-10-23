"""Coleta assistida: o usuário abre cada produto no próprio Chrome (um clique por produto) e uma extensão envia
a página lida e o print. Aqui ficam a fila da sessão, o registro de cada captura e o fechamento da execução.

As regras são as mesmas da coleta automática: classificação de status, preço suspeito, alertas por e-mail.
"""
import base64
import binascii
import hmac
import json
import os
import re
import secrets
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .adapters import adaptador_para
from .alerts import servico as alertas
from .alerts.servico import Notificador
from .core.coleta import Resultado, _config, _nome_arquivo, _salvar_coleta, _selecionar, _status_final
from .core.lojas import modelo_simples
from .core.precos import formatar_brl, parse_preco_centavos
from .core.status import StatusColeta
from .core.validacao import Leitura, classificar
from .db.models import Alerta, Coleta, Configuracao, Execucao, Produto, RevisaoLink
from .db.session import BACKEND_DIR, PRINTS_DIR

TOKEN_PATH = Path(os.environ.get("SEARCHING_TOKEN") or BACKEND_DIR / "data" / "assistida.token")
CHAVE_SESSAO = "assistida_sessao"
LIMITE_PRINT_BYTES = 15 * 1024 * 1024
_PNG = b"\x89PNG\r\n\x1a\n"


class SessaoInvalida(ValueError):
    pass


# ---------- token da extensão ----------
def obter_token(caminho: Path | None = None) -> str:
    """Segredo compartilhado com a extensão. Fica só neste computador (backend/data/, fora do Git)."""
    caminho = Path(caminho or TOKEN_PATH)
    if caminho.exists() and caminho.read_text().strip():
        return caminho.read_text().strip()
    caminho.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(32)
    caminho.write_text(token)
    return token


def token_valido(recebido: str | None, caminho: Path | None = None) -> bool:
    return bool(recebido) and hmac.compare_digest(str(recebido), obter_token(caminho))


# ---------- estado da sessão (uma por vez, guardada em configuracoes) ----------
def _ler(s: Session) -> dict | None:
    c = s.get(Configuracao, CHAVE_SESSAO)
    return json.loads(c.valor) if c and c.valor else None


def _gravar(s: Session, dados: dict | None) -> None:
    if dados is None:
        c = s.get(Configuracao, CHAVE_SESSAO)
        if c:
            s.delete(c)
    else:
        s.merge(Configuracao(chave=CHAVE_SESSAO, valor=json.dumps(dados)))


def _print_url(caminho: str | None) -> str | None:
    if not caminho:
        return None
    partes = caminho.replace("\\", "/").split("/")
    return f"/api/prints/{partes[-2]}/{partes[-1]}" if len(partes) >= 2 else None


def _reais(centavos: int | None) -> str | None:
    return formatar_brl(centavos) if centavos is not None else None


def _json_coleta(s: Session, c: Coleta) -> dict:
    anterior = s.scalar(
        select(Coleta.preco_pix_centavos)
        .where(
            Coleta.produto_id == c.produto_id, Coleta.status == StatusColeta.OK.value,
            Coleta.preco_pix_centavos.is_not(None), Coleta.coletado_em < c.coletado_em,
        )
        .order_by(Coleta.coletado_em.desc())
        .limit(1)
    )
    variacao = None
    if c.preco_pix_centavos is not None and anterior:
        variacao = round((c.preco_pix_centavos - anterior) / anterior * 100, 2)
    alerta = s.scalars(select(Alerta).where(Alerta.coleta_id == c.id).limit(1)).first()
    return {
        "id": c.id, "status": c.status, "detalhe": c.erro_detalhe, "titulo": c.titulo_lido, "vendedor": c.vendedor,
        "pix": _reais(c.preco_pix_centavos), "cartao_1x": _reais(c.preco_cartao_1x_centavos),
        "pix_centavos": c.preco_pix_centavos, "cartao_1x_centavos": c.preco_cartao_1x_centavos,
        "preco_anterior": _reais(anterior), "variacao_pct": variacao,
        "print_url": _print_url(c.caminho_print), "coletado_em": c.coletado_em.isoformat(timespec="seconds"),
        "alerta": {"enviado": alerta.sucesso, "erro": alerta.erro} if alerta else None,
    }


def sessao(s: Session) -> dict:
    """Fila da sessão aberta, reconstruída do banco (sobrevive a recarregar a página)."""
    dados = _ler(s)
    if not dados:
        return {"ativa": False}
    execucao = s.get(Execucao, dados["execucao_id"])
    itens, atual = [], None
    for pid in dados["produtos"]:
        p = s.get(Produto, pid)
        ultima = s.scalars(
            select(Coleta).where(Coleta.execucao_id == execucao.id, Coleta.produto_id == pid).order_by(Coleta.id.desc()).limit(1)
        ).first()
        pulado = pid in dados["pulados"]
        item = {
            "produto_id": pid, "nome": p.nome_comercial, "loja": p.loja, "url": p.url_atual,
            "pulado": pulado, "concluido": bool(ultima) or pulado, "coleta": _json_coleta(s, ultima) if ultima else None,
        }
        itens.append(item)
        if atual is None and not item["concluido"]:
            atual = pid
    return {
        "ativa": True, "execucao_id": execucao.id, "iniciada_em": execucao.iniciada_em.isoformat(timespec="seconds"),
        "total": len(itens), "concluidos": sum(1 for i in itens if i["concluido"]), "proximo_produto_id": atual, "itens": itens,
    }


def iniciar(s: Session, stores=None, include=None, exclude=None, adaptador_de=adaptador_para, agora: datetime | None = None) -> dict:
    anterior = _ler(s)
    if anterior:
        encerrar(s, anterior["execucao_id"], notificador=None)
    produtos = [p for p in _selecionar(s, stores, include, exclude) if adaptador_de(p.url_atual) is not None]
    if not produtos:
        raise SessaoInvalida("Nenhum produto ativo de uma loja com suporte para coletar.")
    execucao = Execucao(iniciada_em=agora or datetime.now(), origem="assistida", total=len(produtos))
    s.add(execucao)
    s.flush()
    _gravar(s, {"execucao_id": execucao.id, "produtos": [p.id for p in produtos], "pulados": []})
    s.commit()
    return sessao(s)


def _validar(s: Session, execucao_id: int, produto_id: int) -> tuple[dict, Produto]:
    dados = _ler(s)
    if not dados or dados["execucao_id"] != execucao_id:
        raise SessaoInvalida("Sessão de coleta assistida não está aberta (inicie de novo).")
    if produto_id not in dados["produtos"]:
        raise SessaoInvalida("Produto não faz parte desta sessão.")
    return dados, s.get(Produto, produto_id)


# ---------- print ----------
def salvar_print(data_url: str | None, produto: Produto, quando: datetime, prints_dir: Path = PRINTS_DIR) -> str | None:
    """Grava o PNG enviado pela extensão (data URL) em prints/AAAA-MM-DD/<modelo>_<hora>.png."""
    if not data_url:
        return None
    try:
        bruto = base64.b64decode(data_url.split(",", 1)[-1], validate=False)
    except (binascii.Error, ValueError):
        raise SessaoInvalida("Print inválido (base64).") from None
    if not bruto.startswith(_PNG) or len(bruto) > LIMITE_PRINT_BYTES:
        raise SessaoInvalida("O print precisa ser um PNG de até 15 MB.")
    pasta = Path(prints_dir) / f"{quando:%Y-%m-%d}"
    pasta.mkdir(parents=True, exist_ok=True)
    base = f"{_nome_arquivo(modelo_simples(produto.nome_comercial))}_{quando:%H-%M-%S}"
    destino, n = pasta / f"{base}.png", 2
    while destino.exists():
        destino, n = pasta / f"{base}_{n}.png", n + 1
    destino.write_bytes(bruto)
    return destino.relative_to(BACKEND_DIR).as_posix() if destino.is_relative_to(BACKEND_DIR) else str(destino)


# ---------- registros ----------
def registrar_captura(
    s: Session, execucao_id: int, produto_id: int, dados_captura: dict,
    notificador: Notificador | None = None, prints_dir: Path = PRINTS_DIR, agora: datetime | None = None,
    adaptador_de=adaptador_para,
) -> dict:
    """Recebe o que a extensão leu (HTML da página, HTML com o menu de pagamento aberto e o print) e grava a coleta."""
    _, produto = _validar(s, execucao_id, produto_id)
    html, url_final = dados_captura.get("html"), dados_captura.get("url_final") or produto.url_atual
    if not isinstance(html, str) or not html.strip():
        raise SessaoInvalida("A captura não trouxe o HTML da página.")
    adaptador = adaptador_de(url_final) or adaptador_de(produto.url_atual)
    if adaptador is None:
        raise SessaoInvalida("Esta loja não tem suporte à coleta assistida.")

    agora = agora or datetime.now()
    leitura: Leitura = adaptador.ler_html(html, url_final, dados_captura.get("html_modal"))
    pix = parse_preco_centavos(leitura.pix_texto)
    status, detalhe = classificar(leitura, pix, produto.marca, produto.modelo, produto.armazenamento, produto.extras)
    resultado = Resultado(
        status, detalhe, leitura, salvar_print(dados_captura.get("screenshot"), produto, agora, prints_dir),
        pix, parse_preco_centavos(leitura.cartao_texto),
    )

    cfg = _config(s)
    status, detalhe = _status_final(s, produto, resultado, cfg)
    coleta = _salvar_coleta(s, execucao_id, produto, resultado, status, detalhe)
    if status == StatusColeta.OK:
        alertas.processar_coleta(s, produto, coleta, cfg, notificador or Notificador())
    return _json_coleta(s, coleta)


def registrar_link_quebrado(s: Session, execucao_id: int, produto_id: int) -> dict:
    """O usuário viu que o link não leva ao produto: registra a falha e põe o produto na fila de revisão."""
    _, produto = _validar(s, execucao_id, produto_id)
    resultado = Resultado(StatusColeta.LINK_QUEBRADO, "marcado como quebrado pelo usuário na coleta assistida")
    coleta = _salvar_coleta(s, execucao_id, produto, resultado, resultado.status, resultado.detalhe)
    if not s.scalar(select(RevisaoLink.id).where(RevisaoLink.produto_id == produto.id, RevisaoLink.estado == "pendente")):
        s.add(RevisaoLink(produto_id=produto.id, execucao_id=execucao_id, motivo=StatusColeta.LINK_QUEBRADO.value, candidatos=[]))
        s.commit()
    return _json_coleta(s, coleta)


def pular(s: Session, execucao_id: int, produto_id: int) -> dict:
    dados, _ = _validar(s, execucao_id, produto_id)
    if produto_id not in dados["pulados"]:
        dados["pulados"].append(produto_id)
        _gravar(s, dados)
        s.commit()
    return sessao(s)


def encerrar(s: Session, execucao_id: int, notificador: Notificador | None = None, agora: datetime | None = None) -> dict:
    """Fecha a execução com os totais (uma coleta final por produto) e, se ligado, envia o resumo por e-mail."""
    execucao = s.get(Execucao, execucao_id)
    if execucao is None:
        raise SessaoInvalida("Execução não encontrada.")
    dados = _ler(s)
    ids = dados["produtos"] if dados and dados["execucao_id"] == execucao_id else []
    por_status: dict[str, int] = {}
    for pid in ids:
        ultima = s.scalars(
            select(Coleta).where(Coleta.execucao_id == execucao_id, Coleta.produto_id == pid).order_by(Coleta.id.desc()).limit(1)
        ).first()
        if ultima:
            por_status[ultima.status] = por_status.get(ultima.status, 0) + 1

    if execucao.finalizada_em is None:
        execucao.finalizada_em = agora or datetime.now()
        execucao.ok = por_status.get(StatusColeta.OK.value, 0)
        execucao.falhas = sum(por_status.values()) - execucao.ok
        execucao.em_revisao = len(s.scalars(select(RevisaoLink.id).where(RevisaoLink.execucao_id == execucao_id)).all())
    resumo = {
        "execucao_id": execucao_id, "total": execucao.total, "coletados": sum(por_status.values()),
        "ok": execucao.ok, "falhas": execucao.falhas, "links_corrigidos": 0, "em_revisao": execucao.em_revisao,
        "alertas": len(s.scalars(select(Alerta.id).join(Coleta, Alerta.coleta_id == Coleta.id).where(Coleta.execucao_id == execucao_id)).all()),
        "por_status": por_status, "pulados": len(dados["pulados"]) if dados and dados["execucao_id"] == execucao_id else 0,
    }
    if dados and dados["execucao_id"] == execucao_id:
        _gravar(s, None)
    s.commit()
    if notificador is not None and _config(s)["resumo_diario_email"] == "1" and resumo["coletados"] > 0:
        alertas.enviar_resumo({**resumo, "total": resumo["coletados"]}, notificador)
    return resumo
