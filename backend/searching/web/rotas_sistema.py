"""Rotas do sistema: verificação de saúde do servidor e coleta automática manual (só modo local)."""
from flask import Blueprint, jsonify

from . import coleta_cli
from .comum import corpo_json

bp = Blueprint("sistema", __name__)


@bp.route("/api/health")
def api_health():
    return jsonify({"status": "Servidor Flask rodando"})


@bp.route("/api/coletar", methods=["POST"])
def coletar_manual():
    """Executa a coleta manual dos preços e retorna resumo detalhado."""
    try:
        data = corpo_json()
        stores = data.get("stores", [])
        include = data.get("include", [])
        exclude = data.get("exclude", [])

        print("===========================================")
        print("🚀 Iniciando coleta manual...")
        print(f"🛒 Filtros -> Stores: {stores}, Include: {include}, Exclude: {exclude}")

        # Mesmo comando da linha de comando: python -m searching.run
        codigo, resumo = coleta_cli.rodar_coleta_cli("manual", stores, include, exclude)
        if codigo == 2:
            return jsonify({"ok": False, "error": "Já existe uma coleta em andamento. Aguarde terminar."}), 409
        if codigo != 0:
            return jsonify({"ok": False, "error": resumo.get("erro", "Falha na coleta")}), 500

        print(f"✅ Coleta concluída - {resumo}")

        return jsonify({
            "ok": True,
            "message": f"Coleta concluída: {resumo['ok']} de {resumo['total']} com sucesso, {resumo['falhas']} com falha.",
            "pasta": resumo["pasta"],
            "linhas": resumo["total"],
            "resumo": resumo,
            "detalhes": {"stores": stores, "include": include, "exclude": exclude},
        })

    except Exception as e:
        print(f"[ERRO] Falha na coleta manual: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500
