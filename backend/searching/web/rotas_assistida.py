"""Rotas da coleta assistida: fila da pessoa, autorização e captura da extensão."""
from flask import Blueprint, current_app, g, jsonify
from sqlalchemy import select

from .. import assistida, modo
from ..db.models import Atribuicao, Produto
from .comum import corpo_json, fabrica, uid

bp = Blueprint("assistida", __name__)


def _executar(acao):
    """Executa uma ação da coleta assistida dentro de uma sessão do banco, traduzindo erros de validação em 400."""
    try:
        with fabrica()() as s:
            return jsonify(acao(s))
    except assistida.LimiteExcedido as e:
        return jsonify({"error": str(e), "aguardar_ms": e.aguardar_ms}), e.status
    except (assistida.SessaoInvalida, ValueError, TypeError) as e:
        return jsonify({"error": str(e)}), 400


def _ids(d):
    return int(d.get("execucao_id", 0)), int(d.get("produto_id", 0))


def _produtos_do_coletor(s):
    """Hospedado: coletor só coleta o que lhe foi atribuído (admin: tudo). Local: tudo (None)."""
    if not modo.hospedado() or g.usuario.papel == "admin":
        return None
    return set(s.scalars(select(Atribuicao.produto_id).where(Atribuicao.usuario_id == g.usuario.id)))


@bp.route("/api/assistida/token", methods=["GET"])
def token():
    """Segredo que a página entrega à extensão no pareamento local (a resposta não é legível por outros sites: sem CORS)."""
    return jsonify({"token": assistida.obter_token(), "servidor": f"http://127.0.0.1:{current_app.config['PORTA']}"})


@bp.route("/api/assistida/sessao", methods=["GET"])
def sessao():
    return _executar(lambda s: assistida.sessao(s, uid()))


@bp.route("/api/assistida/iniciar", methods=["POST"])
def iniciar():
    data = corpo_json()
    return _executar(lambda s: assistida.iniciar(
        s, data.get("stores"), data.get("include"), data.get("exclude"), usuario_id=uid(), permitidos=_produtos_do_coletor(s)
    ))


@bp.route("/api/assistida/em-coleta", methods=["GET"])
def em_coleta():
    """Quem está coletando o quê agora (evita duas pessoas no mesmo produto)."""
    with fabrica()() as s:
        return jsonify([
            {"produto_id": pid, "produto": s.get(Produto, pid).nome_comercial, "por": info["usuario"], "desde": info["desde"]}
            for pid, info in assistida.em_coleta(s).items()
        ])


@bp.route("/api/assistida/captura", methods=["POST"])
def captura():
    # a guarda já validou o token (por usuário no modo hospedado)
    d = corpo_json()
    return _executar(lambda s: assistida.registrar_captura(
        s, *_ids(d), d, usuario_id=uid(), notificador=current_app.config["NOTIFICADOR"],
    ))


@bp.route("/api/assistida/autorizar", methods=["POST"])
def autorizar():
    """A extensão pergunta antes de abrir cada página: o servidor impõe intervalo mínimo e limite por loja."""
    d = corpo_json()
    return _executar(lambda s: assistida.autorizar_abertura(s, *_ids(d), usuario_id=uid()))


@bp.route("/api/assistida/link-quebrado", methods=["POST"])
def link_quebrado():
    d = corpo_json()
    return _executar(lambda s: assistida.registrar_link_quebrado(s, *_ids(d), usuario_id=uid()))


@bp.route("/api/assistida/pular", methods=["POST"])
def pular():
    d = corpo_json()
    return _executar(lambda s: assistida.pular(s, *_ids(d), usuario_id=uid()))


@bp.route("/api/assistida/encerrar", methods=["POST"])
def encerrar():
    d = corpo_json()
    return _executar(lambda s: assistida.encerrar(
        s, int(d.get("execucao_id", 0)), notificador=current_app.config["NOTIFICADOR"], usuario_id=uid()
    ))
