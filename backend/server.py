from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
import pandas as pd
import os
import re
import json
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from tzlocal import get_localzone

# sua coleta original (mantida)
from main import coletar_precos

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

app = Flask(__name__)
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

def _load_config():
    default = {
        "enabled": False,
        "times": [],
        "days": ["mon","tue","wed","thu","fri"],
        "stores": [],
        "include": [],
        "exclude": []
    }
    if not os.path.exists(CONFIG_PATH):
        return default
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        cfg.setdefault("enabled", False)
        cfg.setdefault("times", [])
        cfg.setdefault("days", ["mon","tue","wed","thu","fri"])
        cfg.setdefault("stores", [])
        cfg.setdefault("include", [])
        cfg.setdefault("exclude", [])
        return cfg
    except Exception:
        return default

def _save_config(cfg):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

def _validate_time_str(t):
    return bool(re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", str(t).strip()))

def _days_to_cron(days):
    pt = {"seg":"mon","ter":"tue","qua":"wed","qui":"thu","sex":"fri","sab":"sat","dom":"sun"}
    norm = [(pt.get(str(d).lower().strip(), str(d).lower().strip())) for d in days]
    valid = [d for d in norm if d in ["mon","tue","wed","thu","fri","sat","sun"]]
    return ",".join(valid) if valid else "mon,tue,wed,thu,fri"

# ==============================
# Scheduler (mantido)
# ==============================
local_tz = str(get_localzone())
scheduler = BackgroundScheduler(timezone=local_tz)

def _unschedule_all():
    for job in list(scheduler.get_jobs()):
        if job.id.startswith("searching-"):
            scheduler.remove_job(job.id)

def _run_collection_job():
    try:
        cfg = _load_config()
        stores = cfg.get("stores", [])
        include = cfg.get("include", [])
        exclude = cfg.get("exclude", [])
        df, pasta = coletar_precos(stores=stores, include=include, exclude=exclude)
        print(f"[AUTO] Coleta OK {datetime.now().isoformat()} - pasta: {pasta} - linhas: {len(df)}")
    except Exception as e:
        print(f"[AUTO] ERRO na coleta automática: {e}")

def _schedule_from_config(cfg):
    _unschedule_all()
    if not cfg.get("enabled"):
        return
    cron_days = _days_to_cron(cfg.get("days", []))
    for i, t in enumerate(cfg.get("times", [])):
        if not _validate_time_str(t):
            continue
        hh, mm = t.split(":")
        trig = CronTrigger(day_of_week=cron_days, hour=int(hh), minute=int(mm), timezone=local_tz)
        scheduler.add_job(_run_collection_job, trig, id=f"searching-job-{i}", replace_existing=True)

cfg0 = _load_config()
_schedule_from_config(cfg0)
scheduler.start()

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
    if not os.path.exists(HIST_PATH) or os.path.getsize(HIST_PATH) == 0:
        return jsonify([])

    try:
        # Lê CSV com separador ';' (compatível com o main.py)
        df = read_csv_safe(HIST_PATH, prefer_semicolon=True).fillna("")
        df.columns = [c.strip() for c in df.columns]

        # Garante as colunas essenciais
        expected_cols = [
            "DATA", "NOME", "MODELO", "SITE", "ENTREGUE_POR",
            "PIX", "CREDITO", "STATUS", "LINK"
        ]
        for col in expected_cols:
            if col not in df.columns:
                df[col] = ""

        # Corrige nomes legados (ex: LOJA → SITE)
        if "LOJA" in df.columns and "SITE" not in df.columns:
            df["SITE"] = df["LOJA"]

        # Converte para lista de dicionários
        dados = df.to_dict(orient="records")
        return jsonify(dados)

    except Exception as e:
        print(f"[ERRO] Falha ao ler histórico: {e}")
        return jsonify([])


# ==============================
# Rotas: Scheduler (mantidas)
# ==============================
@app.route("/api/schedule", methods=["GET"])
def schedule_get():
    cfg = _load_config()
    jobs = []
    for job in scheduler.get_jobs():
        if job.id.startswith("searching-"):
            jobs.append({
                "id": job.id,
                "next_run": job.next_run_time.isoformat() if job.next_run_time else None
            })
    return jsonify({"config": cfg, "jobs": jobs, "timezone": local_tz})

@app.route("/api/schedule", methods=["POST"])
def schedule_set():
    data = request.get_json(force=True, silent=True) or {}
    enabled = bool(data.get("enabled", False))
    times = data.get("times", [])
    days = data.get("days", [])
    stores = data.get("stores", [])
    include = data.get("include", [])
    exclude = data.get("exclude", [])

    good_times = [t for t in times if _validate_time_str(t)]
    cfg = {
        "enabled": enabled,
        "times": sorted(set(good_times)),
        "days": days,
        "stores": stores if isinstance(stores, list) else [],
        "include": include if isinstance(include, list) else [],
        "exclude": exclude if isinstance(exclude, list) else [],
    }
    _save_config(cfg)
    _schedule_from_config(cfg)

    jobs = []
    for job in scheduler.get_jobs():
        if job.id.startswith("searching-"):
            jobs.append({
                "id": job.id,
                "next_run": job.next_run_time.isoformat() if job.next_run_time else None
            })
    return jsonify({"message": "Agendamento atualizado", "config": cfg, "jobs": jobs})

@app.route("/")
def home():
    return jsonify({"status": "Servidor Flask rodando 🚀"})

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

        # Usa a função principal do main.py
        df, pasta = coletar_precos(stores=stores, include=include, exclude=exclude)

        # Monta resposta detalhada
        colunas = list(df.columns) if not df.empty else []
        linhas = len(df)
        print(f"✅ Coleta concluída - {linhas} registros - Pasta: {pasta}")

        return jsonify({
            "ok": True,
            "message": "Coleta concluída com sucesso!",
            "pasta": pasta,
            "linhas": linhas,
            "colunas": colunas,
            "arquivo": os.path.basename(HIST_PATH),
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
    print(f"   🕒 Timezone: {local_tz}")
    print("   📂 Lendo histórico: data/historico.csv")
    print("   📄 Lendo links: links.csv")
    print("===========================================")
    app.run(host="0.0.0.0", port=5000, debug=True)
