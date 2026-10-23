from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
import pandas as pd
import os
import re
import json
from datetime import datetime

import subprocess
import sys

from sqlalchemy import select

from searching import agendamento
from searching.core.precos import formatar_brl
from searching.db.models import Coleta, Produto
from searching.db.session import criar_engine, iniciar_banco

# ==============================
# Caminhos / init
# ==============================
BASE_DIR = os.path.dirname(__file__)
DATA_DIR = os.path.join(BASE_DIR, "data")
PRINTS_DIR = os.path.join(BASE_DIR, "prints")
LINKS_PATH = os.path.join(BASE_DIR, "links.csv")
HIST_PATH = os.path.join(DATA_DIR, "historico.csv")
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
# Utils
# ==============================
def read_csv_safe(path, prefer_semicolon=True):
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return pd.DataFrame()
    if prefer_semicolon:
        try:
            return pd.read_csv(path, sep=";", encoding="utf-8-sig", engine="python")
        except Exception:
            pass
    return pd.read_csv(path, sep=None, engine="python", encoding="utf-8")

def _infer_store(url: str) -> str:
    u = (str(url) or "").lower()
    if "magazineluiza" in u or "magalu" in u:
        return "Magazine Luiza"
    if "amazon" in u:
        return "Amazon"
    if "casasbahia" in u:
        return "Casas Bahia"
    return ""

def _normalize_links_df(df: pd.DataFrame) -> pd.DataFrame:
    """Garante colunas ['NOME COMERCIAL','LINK','LOJA'] e preenche LOJA por inferência quando faltar."""
    if df is None or df.empty:
        return pd.DataFrame(columns=["NOME COMERCIAL", "LINK", "LOJA"])

    cols = [c.strip() for c in df.columns]
    df.columns = cols

    # mapas comuns de nomes
    rename_map = {}
    if "NOME" in cols and "NOME COMERCIAL" not in cols:
        rename_map["NOME"] = "NOME COMERCIAL"
    if "URL" in cols and "LINK" not in cols:
        rename_map["URL"] = "LINK"

    if rename_map:
        df = df.rename(columns=rename_map)

    # cria coluna LOJA se não existir
    if "LOJA" not in df.columns:
        df["LOJA"] = ""

    # preenche LOJA vazia por inferência do link
    if "LINK" in df.columns:
        df["LOJA"] = df.apply(
            lambda r: (r.get("LOJA") or "").strip() or _infer_store(r.get("LINK", "")),
            axis=1
        )
    else:
        # caso extremo: sem LINK (mantém estrutura)
        df["LINK"] = df.get("LINK", "")

    # ordena e remove espaços no header
    df = df[["NOME COMERCIAL", "LINK", "LOJA"]]
    return df

def _persist_links_df(df: pd.DataFrame):
    df.to_csv(LINKS_PATH, sep=";", index=False, encoding="utf-8-sig")

# ==============================
# Rotas: LINKS
# ==============================
@app.route("/api/links", methods=["GET"])
def listar_links():
    if not os.path.exists(LINKS_PATH) or os.path.getsize(LINKS_PATH) == 0:
        return jsonify([])
    df = read_csv_safe(LINKS_PATH)
    df = _normalize_links_df(df)

    # se houver LOJA inferida que não estava gravada, persistimos para padronizar
    _persist_links_df(df)
    return jsonify(df.to_dict(orient="records"))

@app.route("/api/links", methods=["POST"])
def adicionar_link():
    data = request.get_json(force=True, silent=True) or {}
    nome = (data.get("nome") or "").strip()
    link = (data.get("link") or "").strip()
    loja = (data.get("loja") or "").strip() or _infer_store(link)

    if not nome or not link:
        return jsonify({"error": "Campos obrigatórios: nome e link"}), 400

    novo = pd.DataFrame([[nome, link, loja]], columns=["NOME COMERCIAL", "LINK", "LOJA"])

    if os.path.exists(LINKS_PATH) and os.path.getsize(LINKS_PATH) > 0:
        antigo = _normalize_links_df(read_csv_safe(LINKS_PATH))
        df_final = pd.concat([antigo, novo], ignore_index=True)
    else:
        df_final = novo

    _persist_links_df(df_final)
    return jsonify({"message": "Link adicionado com sucesso!"})

@app.route("/api/links", methods=["PUT"])
def editar_link():
    data = request.get_json(force=True, silent=True) or {}
    original_nome = data.get("originalNome")
    original_link = data.get("originalLink")
    original_loja = data.get("originalLoja", "")

    novo_nome = data.get("nome")
    novo_link = data.get("link")
    nova_loja = data.get("loja") or _infer_store(novo_link)

    if not os.path.exists(LINKS_PATH):
        return jsonify({"error": "links.csv não encontrado"}), 404

    df = _normalize_links_df(read_csv_safe(LINKS_PATH))
    mask = (df["NOME COMERCIAL"] == original_nome) & (df["LINK"] == original_link)
    # se havia loja na origem, filtra também
    if original_loja:
        mask = mask & (df["LOJA"] == original_loja)

    if not mask.any():
        return jsonify({"error": "Link não encontrado"}), 404

    df.loc[mask, "NOME COMERCIAL"] = novo_nome
    df.loc[mask, "LINK"] = novo_link
    df.loc[mask, "LOJA"] = nova_loja

    _persist_links_df(df)
    return jsonify({"message": "Link atualizado com sucesso!"})

@app.route("/api/links", methods=["DELETE"])
def deletar_link():
    data = request.get_json(force=True, silent=True) or {}
    nome = data.get("nome")
    link = data.get("link")
    loja = data.get("loja", "")

    if not os.path.exists(LINKS_PATH):
        return jsonify({"error": "links.csv não encontrado"}), 404

    df = _normalize_links_df(read_csv_safe(LINKS_PATH))
    before = len(df)

    mask = (df["NOME COMERCIAL"] == nome) & (df["LINK"] == link)
    if loja:
        mask = mask & (df["LOJA"] == loja)

    df = df.loc[~mask]

    if len(df) == before:
        return jsonify({"error": "Link não encontrado"}), 404

    _persist_links_df(df)
    return jsonify({"message": "Link removido com sucesso!"})

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
    print("   📄 Lendo links: links.csv")
    print("===========================================")
    app.run(host="0.0.0.0", port=5000, debug=True)
