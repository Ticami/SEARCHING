"""Rotas dos alertas de preço por e-mail: configuração, regras por produto, destinatários e e-mail de teste."""
from flask import Blueprint, current_app, jsonify
from sqlalchemy import select

from ..alerts import config as alertas_config
from ..alerts import destinatarios as alertas_dest
from ..alerts import email as alertas_email
from ..alerts import regras as alertas_regras
from ..alerts import servico as alertas_servico
from ..auth import guarda
from ..core.precos import formatar_brl
from ..db import links as repo_links
from ..db.models import Alerta, Produto
from .comum import corpo_json, fabrica

bp = Blueprint("alertas", __name__)


def _alerta_json(a, p):
    return {
        "id": a.id, "produto_id": p.id, "produto": p.nome_comercial, "loja": p.loja,
        "preco_anterior": formatar_brl(a.preco_anterior_centavos), "preco_atual": formatar_brl(a.preco_atual_centavos),
        "queda_pct": a.queda_pct, "base_preco": a.base_preco, "motivos": a.motivos,
        "enviado_em": a.enviado_em.isoformat(timespec="seconds"), "destinatario": a.destinatario,
        "sucesso": a.sucesso, "erro": a.erro,
    }


def _regra_json(p):
    return {
        "produto_id": p.id, "nome": p.nome_comercial, "loja": p.loja,
        "alerta_pct": p.alerta_pct, "alerta_base": p.alerta_base,
        "alerta_preco_alvo": p.alerta_preco_alvo_centavos / 100 if p.alerta_preco_alvo_centavos is not None else None,
    }


@bp.route("/api/alertas", methods=["GET"])
def listar_alertas():
    with fabrica()() as s:
        linhas = s.execute(
            select(Alerta, Produto).join(Produto, Alerta.produto_id == Produto.id).order_by(Alerta.id.desc()).limit(200)
        ).all()
        return jsonify({
            "smtp": alertas_email.status_config(),
            "destinatarios": {"configurados": alertas_dest.configurados(s)},
            "config": alertas_config.ler_config(s),
            "alertas": [_alerta_json(a, p) for a, p in linhas],
        })


@bp.route("/api/alertas/config", methods=["PUT"])
def salvar_config_alertas():
    with fabrica()() as s:
        try:
            config = alertas_config.salvar_config(s, corpo_json())
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        s.commit()
        return jsonify({"message": "Configuração de alertas salva.", "config": config})


@bp.route("/api/alertas/regras", methods=["GET"])
def listar_regras_alerta():
    with fabrica()() as s:
        return jsonify([_regra_json(p) for p in repo_links.listar_ativos(s)])


@bp.route("/api/alertas/regras/<int:produto_id>", methods=["PUT"])
def salvar_regra_alerta(produto_id):
    """Regra própria do produto; campo vazio/null volta a usar o padrão global."""
    data = corpo_json()
    with fabrica()() as s:
        p = s.get(Produto, produto_id)
        if p is None:
            return jsonify({"error": "Produto não encontrado"}), 404
        negado = guarda.exigir_dono(p.id)
        if negado:
            return negado
        try:
            pct = data.get("alerta_pct")
            p.alerta_pct = None if pct in (None, "") else float(str(pct).replace(",", "."))
            if p.alerta_pct is not None and not 0 < p.alerta_pct <= 100:
                raise ValueError("A queda mínima deve estar entre 0 e 100")
            base = data.get("alerta_base") or None
            if base is not None and base not in alertas_regras.BASES_COMPARACAO:
                raise ValueError("Base de comparação inválida")
            p.alerta_base = base
            alvo = data.get("alerta_preco_alvo")
            p.alerta_preco_alvo_centavos = None if alvo in (None, "") else round(float(str(alvo).replace(",", ".")) * 100)
            if p.alerta_preco_alvo_centavos is not None and p.alerta_preco_alvo_centavos <= 0:
                raise ValueError("O preço-alvo deve ser maior que zero")
        except ValueError as e:
            s.rollback()
            return jsonify({"error": str(e) if str(e) and "could not convert" not in str(e) else "Valor numérico inválido"}), 400
        s.commit()
        return jsonify({"message": "Regra salva.", "regra": _regra_json(p)})


@bp.route("/api/alertas/destinatarios", methods=["PUT"])
def salvar_destinatarios():
    """Quem recebe os e-mails (a senha do SMTP continua só no .env). Lista vazia = volta a valer o .env."""
    with fabrica()() as s:
        try:
            lista = alertas_dest.salvar(s, corpo_json().get("destinatarios", []))
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        s.commit()
        return jsonify({"message": "Destinatários salvos.", "configurados": lista})


@bp.route("/api/alertas/teste", methods=["POST"])
def enviar_email_de_teste():
    with fabrica()() as s:
        ok, mensagem = alertas_servico.enviar_teste(current_app.config["NOTIFICADOR"], s=s)
    return jsonify({"ok": ok, "message": mensagem}), (200 if ok else 500)
