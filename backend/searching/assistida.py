"""Coleta assistida: o usuário abre cada produto no próprio Chrome (um clique por produto) e uma extensão envia
a página lida e o print. Aqui ficam a fila da sessão, o registro de cada captura e o fechamento da execução.

As regras são as mesmas da coleta automática: classificação de status, preço suspeito, alertas por e-mail.
"""
import base64
import binascii
import hmac
import json
import os
import secrets
from datetime import datetime, timedelta
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
from .db.models import AberturaPagina, Alerta, Coleta, Configuracao, Execucao, Produto, RevisaoLink, Usuario
from .db.session import BACKEND_DIR, PRINTS_DIR

TOKEN_PATH = Path(os.environ.get("SEARCHING_TOKEN") or BACKEND_DIR / "data" / "assistida.token")
CHAVE_SESSAO = "assistida_sessao"
LIMITE_PRINT_BYTES = 15 * 1024 * 1024
_PNG = b"\x89PNG\r\n\x1a\n"


class SessaoInvalida(ValueError):
    status = 400


class LimiteExcedido(SessaoInvalida):
    """Abertura de página negada pelo servidor: intervalo mínimo, limite da loja ou produto em coleta por outra pessoa."""

    def __init__(self, mensagem: str, status: int = 429, aguardar_ms: int = 0):
        super().__init__(mensagem)
        self.status, self.aguardar_ms = status, aguardar_ms


INTERVALO_MINIMO_S = 3
SESSAO_ABANDONADA_H = 12  # sessão aberta há mais que isso não trava mais os produtos para os outros


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
def _chave(usuario_id: int | None) -> str:
    """Modo local: uma sessão única (chave antiga). Modo hospedado: uma sessão por usuário."""
    return CHAVE_SESSAO if usuario_id is None else f"{CHAVE_SESSAO}:{usuario_id}"


def _ler(s: Session, usuario_id: int | None = None) -> dict | None:
    c = s.get(Configuracao, _chave(usuario_id))
    return json.loads(c.valor) if c and c.valor else None


def _gravar(s: Session, dados: dict | None, usuario_id: int | None = None) -> None:
    if dados is None:
        c = s.get(Configuracao, _chave(usuario_id))
        if c:
            s.delete(c)
    else:
        s.merge(Configuracao(chave=_chave(usuario_id), valor=json.dumps(dados)))


def em_coleta(s: Session, agora: datetime | None = None, exceto_usuario_id: int | None = None) -> dict[int, dict]:
    """Produtos pendentes na fila de uma sessão ativa de alguém: {produto_id: {usuario_id, usuario, desde}}."""
    agora = agora or datetime.now()
    achados: dict[int, dict] = {}
    for c in s.scalars(select(Configuracao).where(Configuracao.chave.like(f"{CHAVE_SESSAO}:%"))):
        uid = int(c.chave.split(":", 1)[1])
        if uid == exceto_usuario_id:
            continue
        dados = json.loads(c.valor)
        execucao = s.get(Execucao, dados["execucao_id"])
        if execucao is None or agora - execucao.iniciada_em > timedelta(hours=SESSAO_ABANDONADA_H):
            continue
        u = s.get(Usuario, uid)
        for pid in dados["produtos"]:
            if pid in dados["pulados"]:
                continue
            feito = s.scalar(select(Coleta.id).where(Coleta.execucao_id == execucao.id, Coleta.produto_id == pid).limit(1))
            if not feito:
                achados[pid] = {
                    "usuario_id": uid, "usuario": (u.nome or u.email) if u else str(uid),
                    "desde": execucao.iniciada_em.isoformat(timespec="seconds"),
                }
    return achados


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


def sessao(s: Session, usuario_id: int | None = None) -> dict:
    """Fila da sessão aberta, reconstruída do banco (sobrevive a recarregar a página)."""
    dados = _ler(s, usuario_id)
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


def iniciar(
    s: Session, stores=None, include=None, exclude=None, adaptador_de=adaptador_para, agora: datetime | None = None,
    usuario_id: int | None = None, permitidos: set[int] | None = None,
) -> dict:
    """Abre a fila. `permitidos` (modo hospedado) limita aos produtos atribuídos ao coletor; produtos que outra
    pessoa está coletando agora ficam de fora e voltam em `em_coleta_por_outros`."""
    anterior = _ler(s, usuario_id)
    if anterior:
        encerrar(s, anterior["execucao_id"], notificador=None, usuario_id=usuario_id)
    candidatos = [p for p in _selecionar(s, stores, include, exclude) if adaptador_de(p.url_atual) is not None]
    if permitidos is not None:
        candidatos = [p for p in candidatos if p.id in permitidos]
        if not candidatos:
            raise SessaoInvalida("Nenhum produto atribuído a você para coletar. Peça a um administrador.")
    ocupados = em_coleta(s, agora, exceto_usuario_id=usuario_id) if usuario_id is not None else {}
    produtos = [p for p in candidatos if p.id not in ocupados]
    if not produtos:
        if candidatos:
            raise SessaoInvalida("Todos esses produtos já estão em coleta por outra pessoa.")
        raise SessaoInvalida("Nenhum produto ativo de uma loja com suporte para coletar.")
    execucao = Execucao(iniciada_em=agora or datetime.now(), origem="assistida", total=len(produtos), usuario_id=usuario_id)
    s.add(execucao)
    s.flush()
    _gravar(s, {"execucao_id": execucao.id, "produtos": [p.id for p in produtos], "pulados": []}, usuario_id)
    s.commit()
    resposta = sessao(s, usuario_id)
    resposta["em_coleta_por_outros"] = [
        {"produto_id": p.id, "produto": p.nome_comercial, "por": ocupados[p.id]["usuario"]} for p in candidatos if p.id in ocupados
    ]
    return resposta


def _validar(s: Session, execucao_id: int, produto_id: int, usuario_id: int | None = None) -> tuple[dict, Produto]:
    dados = _ler(s, usuario_id)
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
    adaptador_de=adaptador_para, usuario_id: int | None = None,
) -> dict:
    """Recebe o que a extensão leu (HTML da página, HTML com o menu de pagamento aberto e o print) e grava a coleta."""
    _, produto = _validar(s, execucao_id, produto_id, usuario_id)
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
    if usuario_id is not None:
        coleta.coletado_por_id = usuario_id
        s.commit()
    if status == StatusColeta.OK:
        alertas.processar_coleta(s, produto, coleta, cfg, notificador or Notificador())
    return _json_coleta(s, coleta)


def registrar_link_quebrado(s: Session, execucao_id: int, produto_id: int, usuario_id: int | None = None) -> dict:
    """O usuário viu que o link não leva ao produto: registra a falha e põe o produto na fila de revisão."""
    _, produto = _validar(s, execucao_id, produto_id, usuario_id)
    resultado = Resultado(StatusColeta.LINK_QUEBRADO, "marcado como quebrado pelo usuário na coleta assistida")
    coleta = _salvar_coleta(s, execucao_id, produto, resultado, resultado.status, resultado.detalhe)
    if usuario_id is not None:
        coleta.coletado_por_id = usuario_id
    if not s.scalar(select(RevisaoLink.id).where(RevisaoLink.produto_id == produto.id, RevisaoLink.estado == "pendente")):
        s.add(RevisaoLink(produto_id=produto.id, execucao_id=execucao_id, motivo=StatusColeta.LINK_QUEBRADO.value, candidatos=[]))
        s.commit()
    return _json_coleta(s, coleta)


def pular(s: Session, execucao_id: int, produto_id: int, usuario_id: int | None = None) -> dict:
    dados, _ = _validar(s, execucao_id, produto_id, usuario_id)
    if produto_id not in dados["pulados"]:
        dados["pulados"].append(produto_id)
        _gravar(s, dados, usuario_id)
        s.commit()
    return sessao(s, usuario_id)


def autorizar_abertura(
    s: Session, execucao_id: int, produto_id: int, usuario_id: int | None = None, agora: datetime | None = None,
) -> dict:
    """A extensão pergunta antes de abrir cada página. O servidor impõe o intervalo mínimo por pessoa, o limite
    global por loja e a regra de uma pessoa por produto, e registra a abertura."""
    from .auth.servico import auditar

    agora = agora or datetime.now()
    _, produto = _validar(s, execucao_id, produto_id, usuario_id)
    if usuario_id is not None and produto_id in em_coleta(s, agora, exceto_usuario_id=usuario_id):
        raise LimiteExcedido("Este produto está em coleta por outra pessoa.", 409)
    consulta = select(AberturaPagina.em).order_by(AberturaPagina.em.desc()).limit(1)
    if usuario_id is not None:
        consulta = consulta.where(AberturaPagina.usuario_id == usuario_id)
    ultima = s.scalar(consulta)
    if ultima is not None:
        falta = INTERVALO_MINIMO_S - (agora - ultima).total_seconds()
        if falta > 0:
            raise LimiteExcedido("Aguarde: uma página a cada 3 segundos.", 429, int(falta * 1000) + 1)
    limite = int(_config(s).get("limite_loja_hora", "120"))
    na_hora = len(s.scalars(
        select(AberturaPagina.id).where(AberturaPagina.loja == produto.loja, AberturaPagina.em >= agora - timedelta(hours=1))
    ).all())
    if na_hora >= limite:
        auditar(s, "limite_loja", alvo=produto.loja, detalhe={"aberturas_na_ultima_hora": na_hora, "limite": limite}, agora=agora)
        s.commit()
        raise LimiteExcedido(
            f"Limite de {limite} páginas por hora em {produto.loja} atingido (somando todos os usuários). Tente mais tarde.", 429
        )
    s.add(AberturaPagina(em=agora, usuario_id=usuario_id, produto_id=produto_id, loja=produto.loja))
    s.commit()
    return {"ok": True}


def encerrar(
    s: Session, execucao_id: int, notificador: Notificador | None = None, agora: datetime | None = None,
    usuario_id: int | None = None,
) -> dict:
    """Fecha a execução com os totais (uma coleta final por produto) e, se ligado, envia o resumo por e-mail."""
    execucao = s.get(Execucao, execucao_id)
    if execucao is None:
        raise SessaoInvalida("Execução não encontrada.")
    if execucao.usuario_id != usuario_id:
        raise SessaoInvalida("Esta execução pertence a outra pessoa.")
    dados = _ler(s, usuario_id)
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
        _gravar(s, None, usuario_id)
    s.commit()
    if notificador is not None and _config(s)["resumo_diario_email"] == "1" and resumo["coletados"] > 0:
        alertas.enviar_resumo({**resumo, "total": resumo["coletados"]}, notificador)
    return resumo
