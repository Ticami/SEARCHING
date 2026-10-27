"""Rotas de leitura: prints, histórico de coletas, exportação em Excel, galeria e painel de saúde."""
from datetime import datetime
from io import BytesIO

from flask import Blueprint, current_app, jsonify, request, send_file, send_from_directory
import os

from .. import relatorios
from .comum import corpo_json, fabrica

bp = Blueprint("relatorios", __name__)


@bp.route("/api/prints/<pasta>/<filename>")
def get_print(pasta, filename):
    return send_from_directory(os.path.join(current_app.config["PRINTS_DIR"], pasta), filename)


@bp.route("/api/historico", methods=["GET"])
def listar_historico():
    """Histórico de coletas. Filtros opcionais: de, ate (AAAA-MM-DD), loja, produto_id, status."""
    try:
        with fabrica()() as s:
            return jsonify(relatorios.historico(
                s, de=request.args.get("de"), ate=request.args.get("ate"), loja=request.args.get("loja"),
                produto_id=request.args.get("produto_id", type=int), status=request.args.get("status"),
            ))
    except ValueError:
        return jsonify({"error": "Datas devem estar no formato AAAA-MM-DD"}), 400


@bp.route("/api/historico/exportar", methods=["POST"])
def exportar_historico():
    """Excel das coletas pedidas (ids), com preços numéricos e o caminho do print."""
    ids = [int(i) for i in corpo_json().get("ids", []) if str(i).isdigit()]
    try:
        with fabrica()() as s:
            conteudo = relatorios.exportar_excel(s, ids)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    nome = f"relatorio_{datetime.now():%Y%m%d_%H%M}.xlsx"
    return send_file(
        BytesIO(conteudo), as_attachment=True, download_name=nome,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@bp.route("/api/prints-galeria", methods=["GET"])
def galeria_de_prints():
    """Prints ligados às coletas, com o preço da hora. Sem parâmetros devolve as datas disponíveis."""
    data, produto_id = request.args.get("data"), request.args.get("produto_id", type=int)
    try:
        with fabrica()() as s:
            if not data and not produto_id:
                return jsonify({"datas": relatorios.datas_com_prints(s)})
            return jsonify({"itens": relatorios.galeria(s, data=data, produto_id=produto_id)})
    except ValueError:
        return jsonify({"error": "Data deve estar no formato AAAA-MM-DD"}), 400


@bp.route("/api/saude", methods=["GET"])
def painel_de_saude():
    with fabrica()() as s:
        return jsonify(relatorios.saude(s))
