from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
import os
import re
import json
from datetime import datetime

import subprocess
import sys

from sqlalchemy import select

from searching import agendamento
from searching.core.precos import formatar_brl
from searching.db import links as repo_links
from searching.db.models import Coleta, HistoricoLink, Produto, RevisaoLink
from searching.db.session import criar_engine, iniciar_banco

# ==============================
# Caminhos / init
# ==============================
BASE_DIR = os.path.dirname(__file__)
DATA_DIR = os.path.join(BASE_DIR, "data")
PRINTS_DIR = os.path.join(BASE_DIR, "prints")
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(PRINTS_DIR, exist_ok=True)

db_fabrica = iniciar_banco(criar_engine())


def rodar_coleta_cli(origem, stores=None, include=None, exclude=None):
    """Executa a coleta pelo mesmo comando usado pelo agendador: python -m searching.run.

    Devolve (codigo_de_saida, resumo_dict). Código 2 = já existe uma coleta em andamento.
    """
    cmd = [sys.executable, "-m", "searching.run", "--origem", origem]
    for flag, valores in (("--loja", stores), ("--incluir", include), ("--excluir", exclude)):
        for v in valores or []:
            cmd += [flag, str(v)]
    proc = subprocess.run(cmd, cwd=BASE_DIR, capture_output=True, text=True, encoding="utf-8", errors="replace")
    linhas = [l for l in proc.stdout.splitlines() if l.strip()]
    try:
        resumo = json.loads(linhas[-1]) if linhas else {}
    except ValueError:
        resumo = {"erro": (proc.stderr or proc.stdout or "saída inválida do coletor")[-500:]}
    return proc.returncode, resumo


app = Flask(__name__, static_folder="dist", static_url_path="")
CORS(app)

# ==============================
# Rotas: LINKS (banco de dados)
# ==============================
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

@app.route("/api/links", methods=["GET"])
def listar_links():
    with db_fabrica() as s:
        return jsonify([_link_json(p) for p in repo_links.listar_ativos(s)])

@app.route("/api/links", methods=["POST"])
def adicionar_link():
    data = request.get_json(force=True, silent=True) or {}
    try:
        with db_fabrica() as s:
            produto = repo_links.criar(s, data.get("nome"), data.get("link"), data.get("loja"))
            s.commit()
            return jsonify({"message": "Link adicionado com sucesso!", "id": produto.id})
    except repo_links.LinkInvalido as e:
        return jsonify({"error": str(e)}), (409 if "Já existe" in str(e) else 400)

@app.route("/api/links", methods=["PUT"])
def editar_link():
    data = request.get_json(force=True, silent=True) or {}
    try:
        with db_fabrica() as s:
            produto = _produto_do_payload(s, data)
            if produto is None:
                return jsonify({"error": "Link não encontrado"}), 404
            repo_links.atualizar(s, produto, data.get("nome"), data.get("link"), data.get("loja"))
            s.commit()
            return jsonify({"message": "Link atualizado com sucesso!"})
    except repo_links.LinkInvalido as e:
        return jsonify({"error": str(e)}), 409

@app.route("/api/links", methods=["DELETE"])
def deletar_link():
    """Desativa o produto (o histórico de coletas é preservado)."""
    data = request.get_json(force=True, silent=True) or {}
    with db_fabrica() as s:
        produto = _produto_do_payload(s, data)
        if produto is None:
            return jsonify({"error": "Link não encontrado"}), 404
        repo_links.desativar(s, produto)
        s.commit()
        return jsonify({"message": "Link removido com sucesso!"})

@app.route("/api/links/historico", methods=["GET"])
def historico_de_links():
    """Trocas de link (manuais e automáticas), da mais recente para a mais antiga."""
    produto_id = request.args.get("produto_id", type=int)
    with db_fabrica() as s:
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

@app.route("/api/links/historico/<int:historico_id>/reverter", methods=["POST"])
def reverter_troca_de_link(historico_id):
    with db_fabrica() as s:
        h = s.get(HistoricoLink, historico_id)
        if h is None:
            return jsonify({"error": "Troca não encontrada"}), 404
        try:
            repo_links.reverter(s, h)
        except repo_links.LinkInvalido as e:
            return jsonify({"error": str(e)}), 409
        s.commit()
        return jsonify({"message": "Link revertido."})

# ==============================
# Rotas: REVISÃO DE LINKS
# ==============================
def _revisao_json(s, r):
    p = s.get(Produto, r.produto_id)
    ultima = s.scalars(
        select(Coleta).where(Coleta.produto_id == p.id).order_by(Coleta.coletado_em.desc()).limit(1)
    ).first()
    print_url = None
    if ultima and ultima.caminho_print:
        partes = ultima.caminho_print.replace("\\", "/").split("/")
        if len(partes) >= 2:
            print_url = f"/api/prints/{partes[-2]}/{partes[-1]}"
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

@app.route("/api/revisoes", methods=["GET"])
def listar_revisoes():
    estado = request.args.get("estado", "pendente")
    with db_fabrica() as s:
        itens = s.scalars(select(RevisaoLink).where(RevisaoLink.estado == estado).order_by(RevisaoLink.id.desc())).all()
        return jsonify([_revisao_json(s, r) for r in itens])

@app.route("/api/revisoes/<int:revisao_id>/resolver", methods=["POST"])
def resolver_revisao(revisao_id):
    """acao='aprovar' (com o link escolhido ou colado) ou 'desativar' o produto."""
    data = request.get_json(force=True, silent=True) or {}
    with db_fabrica() as s:
        r = s.get(RevisaoLink, revisao_id)
        if r is None:
            return jsonify({"error": "Revisão não encontrada"}), 404
        try:
            repo_links.resolver_revisao(s, r, data.get("acao"), data.get("url"))
        except repo_links.LinkInvalido as e:
            return jsonify({"error": str(e)}), 400
        s.commit()
        return jsonify({"message": "Revisão resolvida."})

# ==============================
# Rotas: PRINTS / HISTÓRICO (mantidas)
# ==============================
@app.route("/api/prints-list", methods=["GET"])
def listar_pastas_prints():
    if not os.path.exists(PRINTS_DIR):
        return jsonify([])
    pastas = sorted([p for p in os.listdir(PRINTS_DIR) if os.path.isdir(os.path.join(PRINTS_DIR, p))], reverse=True)
    return jsonify(pastas)

@app.route("/api/prints-list/<pasta>", methods=["GET"])
def listar_imagens_pasta(pasta):
    pasta_path = os.path.join(PRINTS_DIR, pasta)
    if not os.path.exists(pasta_path):
        return jsonify([])
    imagens = [f for f in os.listdir(pasta_path) if f.lower().endswith((".png", ".jpg", ".jpeg"))]
    return jsonify(imagens)

@app.route("/api/prints/<pasta>/<filename>")
def get_print(pasta, filename):
    return send_from_directory(os.path.join(PRINTS_DIR, pasta), filename)

@app.route("/api/historico", methods=["GET"])
def listar_historico():
    """
    Retorna o histórico de coletas no formato JSON.
    Garante compatibilidade com as novas colunas 'SITE' e 'ENTREGUE_POR'.
    """
    try:
        with db_fabrica() as s:
            linhas = s.execute(
                select(Coleta, Produto).join(Produto, Coleta.produto_id == Produto.id).order_by(Coleta.coletado_em)
            ).all()
            dados = []
            for c, p in linhas:
                dados.append({
                    "DATA": c.coletado_em.strftime("%Y-%m-%d %H:%M:%S"),
                    "NOME": p.nome_comercial,
                    "MODELO": c.titulo_lido or p.nome_comercial,
                    "SITE": p.loja,
                    "ENTREGUE_POR": c.vendedor or "",
                    "PIX": formatar_brl(c.preco_pix_centavos) if c.preco_pix_centavos is not None else "",
                    "CREDITO": formatar_brl(c.preco_cartao_1x_centavos) if c.preco_cartao_1x_centavos is not None else "",
                    "STATUS": c.status,
                    "LINK": p.url_atual,
                    "PRODUTO_ID": p.id,
                    "PIX_CENTAVOS": c.preco_pix_centavos,
                    "CREDITO_CENTAVOS": c.preco_cartao_1x_centavos,
                    "ERRO_DETALHE": c.erro_detalhe or "",
                    "PRINT": c.caminho_print or "",
                })
        return jsonify(dados)

    except Exception as e:
        print(f"[ERRO] Falha ao ler histórico: {e}")
        return jsonify([])


# ==============================
# Rotas: Scheduler (mantidas)
# ==============================
def _estado_agendamento():
    with db_fabrica() as s:
        ultima = agendamento.ultima_execucao(s)
    cfg = agendamento.carregar_config()
    return {
        "config": cfg,
        "tarefa": agendamento.consultar_tarefa(),
        "ultima_execucao": ultima,
        "comando": agendamento.comando_instalacao(cfg["times"] or ["12:00"], agendamento.normalizar_dias(cfg["days"])),
    }

@app.route("/api/schedule", methods=["GET"])
def schedule_get():
    return jsonify(_estado_agendamento())

@app.route("/api/schedule", methods=["POST"])
def schedule_set():
    data = request.get_json(force=True, silent=True) or {}
    cfg = {
        "enabled": bool(data.get("enabled", False)),
        "times": sorted({t for t in data.get("times", []) if agendamento.horario_valido(t)}),
        "days": agendamento.normalizar_dias(data.get("days", [])),
        "stores": data.get("stores") if isinstance(data.get("stores"), list) else [],
        "include": data.get("include") if isinstance(data.get("include"), list) else [],
        "exclude": data.get("exclude") if isinstance(data.get("exclude"), list) else [],
    }
    agendamento.salvar_config(cfg)
    ok, mensagem = agendamento.aplicar(cfg)
    return jsonify({"ok": ok, "message": mensagem, **_estado_agendamento()}), (200 if ok else 500)

@app.route("/api/health")
def api_health():
    return jsonify({"status": "Servidor Flask rodando"})


@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve_frontend(path):
    """
    Servir arquivos do build do frontend (dist).
    Qualquer rota n?o-API cai aqui e devolve index.html para o SPA.
    """
    dist_dir = app.static_folder
    full_path = os.path.join(dist_dir, path)
    if path and os.path.exists(full_path):
        return send_from_directory(dist_dir, path)
    return send_from_directory(dist_dir, "index.html")

@app.route("/api/coletar", methods=["POST"])
def coletar_manual():
    """
    Executa a coleta manual dos preços e retorna resumo detalhado.
    """
    try:
        data = request.get_json(force=True, silent=True) or {}
        stores = data.get("stores", [])
        include = data.get("include", [])
        exclude = data.get("exclude", [])

        print("===========================================")
        print("🚀 Iniciando coleta manual...")
        print(f"🛒 Filtros -> Stores: {stores}, Include: {include}, Exclude: {exclude}")

        # Mesmo comando usado pelo agendamento: python -m searching.run
        codigo, resumo = rodar_coleta_cli("manual", stores, include, exclude)
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
            "detalhes": {
                "stores": stores,
                "include": include,
                "exclude": exclude
            }
        })

    except Exception as e:
        print(f"[ERRO] Falha na coleta manual: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


if __name__ == "__main__":
    print("===========================================")
    print("   🚀 Servidor Flask iniciado com sucesso! ")
    print("   📂 Lendo histórico: data/historico.csv")
    print("   📄 Links no banco de dados (data/searching.db)")
    print("===========================================")
    app.run(host="0.0.0.0", port=5000, debug=True)
