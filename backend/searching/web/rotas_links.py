"""Rotas de links, histórico de trocas de link e fila de revisão."""
from flask import Blueprint, jsonify, request
from sqlalchemy import select

from .. import relatorios
from ..auth import guarda
from ..db import links as repo_links
from ..db.models import Coleta, HistoricoLink, Produto, RevisaoLink
from .comum import corpo_json, fabrica

bp = Blueprint("links", __name__)


def _produto_do_payload(s, data):
    """Localiza o produto pelo id (preferido) ou, por compatibilidade, por nome + link atual."""
    if data.get("id") is not None:
        return s.get(Produto, int(data["id"]))
    nome = data.get("originalNome") or data.get("nome")
    link = data.get("originalLink") or data.get("link")
    loja = data.get("originalLoja") or data.get("loja") or ""
    consulta = select(Produto).where(Produto.ativo.is_(True), Produto.nome_comercial == nome, Produto.url_atual == link)
    if loja:
        consulta = consulta.where(Produto.loja == loja)
    return s.scalars(consulta).first()


def _link_json(p):
    return {"ID": p.id, "NOME COMERCIAL": p.nome_comercial, "LINK": p.url_atual, "LOJA": p.loja}


@bp.route("/api/links", methods=["GET"])
def listar_links():
    with fabrica()() as s:
        return jsonify([_link_json(p) for p in repo_links.listar_ativos(s)])


@bp.route("/api/links", methods=["POST"])
def adicionar_link():
    data = corpo_json()
    try:
        with fabrica()() as s:
            produto = repo_links.criar(s, data.get("nome"), data.get("link"), data.get("loja"))
            s.commit()
            return jsonify({"message": "Link adicionado com sucesso!", "id": produto.id})
    except repo_links.LinkInvalido as e:
        return jsonify({"error": str(e)}), (409 if "Já existe" in str(e) else 400)


@bp.route("/api/links", methods=["PUT"])
def editar_link():
    data = corpo_json()
    try:
        with fabrica()() as s:
            produto = _produto_do_payload(s, data)
            if produto is None:
                return jsonify({"error": "Link não encontrado"}), 404
            negado = guarda.exigir_dono(produto.id)
            if negado:
                return negado
            repo_links.atualizar(s, produto, data.get("nome"), data.get("link"), data.get("loja"))
            s.commit()
            return jsonify({"message": "Link atualizado com sucesso!"})
    except repo_links.LinkInvalido as e:
        return jsonify({"error": str(e)}), 409


@bp.route("/api/links", methods=["DELETE"])
def deletar_link():
    """Desativa o produto (o histórico de coletas é preservado)."""
    data = corpo_json()
    with fabrica()() as s:
        produto = _produto_do_payload(s, data)
        if produto is None:
            return jsonify({"error": "Link não encontrado"}), 404
        repo_links.desativar(s, produto)
        s.commit()
        return jsonify({"message": "Link removido com sucesso!"})


@bp.route("/api/links/historico", methods=["GET"])
def historico_de_links():
    """Trocas de link (manuais e automáticas), da mais recente para a mais antiga."""
    produto_id = request.args.get("produto_id", type=int)
    with fabrica()() as s:
        consulta = select(HistoricoLink, Produto).join(Produto, HistoricoLink.produto_id == Produto.id)
        if produto_id:
            consulta = consulta.where(HistoricoLink.produto_id == produto_id)
        linhas = s.execute(consulta.order_by(HistoricoLink.em.desc(), HistoricoLink.id.desc())).all()
        return jsonify([
            {
                "id": h.id, "produto_id": p.id, "produto": p.nome_comercial, "url_antiga": h.url_antiga,
                "url_nova": h.url_nova, "motivo": h.motivo, "origem": h.origem,
                "nota_confianca": h.nota_confianca, "em": h.em.isoformat(timespec="seconds"),
                "revertivel": p.url_atual == h.url_nova,
            }
            for h, p in linhas
        ])


@bp.route("/api/links/historico/<int:historico_id>/reverter", methods=["POST"])
def reverter_troca_de_link(historico_id):
    with fabrica()() as s:
        h = s.get(HistoricoLink, historico_id)
        if h is None:
            return jsonify({"error": "Troca não encontrada"}), 404
        try:
            repo_links.reverter(s, h)
        except repo_links.LinkInvalido as e:
            return jsonify({"error": str(e)}), 409
        s.commit()
        return jsonify({"message": "Link revertido."})


# ---------- revisão de links ----------
def _revisao_json(s, r):
    p = s.get(Produto, r.produto_id)
    ultima = s.scalars(
        select(Coleta).where(Coleta.produto_id == p.id).order_by(Coleta.coletado_em.desc()).limit(1)
    ).first()
    print_url = relatorios.print_url(ultima.caminho_print) if ultima else None
    return {
        "id": r.id,
        "produto": {"id": p.id, "nome": p.nome_comercial, "loja": p.loja, "url_atual": p.url_atual, "ativo": p.ativo},
        "motivo": r.motivo,
        "candidatos": r.candidatos or [],
        "estado": r.estado,
        "criado_em": r.criado_em.isoformat(timespec="seconds") if r.criado_em else None,
        "ultima_coleta": {
            "status": ultima.status, "erro_detalhe": ultima.erro_detalhe,
            "coletado_em": ultima.coletado_em.isoformat(timespec="seconds"), "print_url": print_url,
        } if ultima else None,
    }


@bp.route("/api/revisoes", methods=["GET"])
def listar_revisoes():
    estado = request.args.get("estado", "pendente")
    with fabrica()() as s:
        itens = s.scalars(select(RevisaoLink).where(RevisaoLink.estado == estado).order_by(RevisaoLink.id.desc())).all()
        return jsonify([_revisao_json(s, r) for r in itens])


@bp.route("/api/revisoes/<int:revisao_id>/resolver", methods=["POST"])
def resolver_revisao(revisao_id):
    """acao='aprovar' (com o link escolhido ou colado) ou 'desativar' o produto."""
    data = corpo_json()
    with fabrica()() as s:
        r = s.get(RevisaoLink, revisao_id)
        if r is None:
            return jsonify({"error": "Revisão não encontrada"}), 404
        negado = guarda.exigir_dono(r.produto_id)
        if negado:
            return negado
        try:
            repo_links.resolver_revisao(s, r, data.get("acao"), data.get("url"))
        except repo_links.LinkInvalido as e:
            return jsonify({"error": str(e)}), 400
        s.commit()
        return jsonify({"message": "Revisão resolvida."})
