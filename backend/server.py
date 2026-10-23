from flask import Flask, jsonify, request, send_file, send_from_directory
from flask_cors import CORS
import os
import re
import json
from datetime import datetime

import subprocess
import sys
from io import BytesIO

from sqlalchemy import select

from searching import agendamento, assistida, relatorios, seguranca
from searching.alerts import config as alertas_config
from searching.alerts import email as alertas_email
from searching.alerts import regras as alertas_regras
from searching.alerts import servico as alertas_servico
from searching.core.precos import formatar_brl
from searching.db import links as repo_links
from searching.db.models import Alerta, Coleta, HistoricoLink, Produto, RevisaoLink
from searching.db.session import PRINTS_DIR as prints_dir_config
from searching.db.session import criar_engine, iniciar_banco

# ==============================
# Caminhos / init
# ==============================
BASE_DIR = os.path.dirname(__file__)
DATA_DIR = os.path.join(BASE_DIR, "data")
PRINTS_DIR = str(prints_dir_config)
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
            cmd.append(f"{flag}={v}")
    proc = subprocess.run(cmd, cwd=BASE_DIR, capture_output=True, text=True, encoding="utf-8", errors="replace")
    linhas = [l for l in proc.stdout.splitlines() if l.strip()]
    try:
        resumo = json.loads(linhas[-1]) if linhas else {}
    except ValueError:
        resumo = {"erro": (proc.stderr or proc.stdout or "saída inválida do coletor")[-500:]}
    return proc.returncode, resumo


# Os prints do servidor têm emoji; com a saída redirecionada (cp1252) isso derrubava o servidor.
for _fluxo in (sys.stdout, sys.stderr):
    if hasattr(_fluxo, "reconfigure"):
        _fluxo.reconfigure(encoding="utf-8", errors="replace")

CONFIG_SERVIDOR = seguranca.configuracao_servidor()
ORIGENS = seguranca.origens_permitidas(porta=CONFIG_SERVIDOR.porta)

app = Flask(__name__, static_folder="dist", static_url_path="")
CORS(app, origins=sorted(ORIGENS))  # só o frontend local; nada de "*"
app.config["MAX_CONTENT_LENGTH"] = 40 * 1024 * 1024  # a captura traz o HTML da página e o print


@app.before_request
def proteger_servidor_local():
    """Recusa Host de fora (DNS rebinding) e escritas vindas de sites que não são o nosso frontend (CSRF)."""
    # A extensão do Chrome envia as capturas com Origin "chrome-extension://..." e prova quem é pelo token secreto.
    da_extensao = request.path == "/api/assistida/captura" and assistida.token_valido(request.headers.get("X-Searching-Token"))
    motivo = seguranca.requisicao_bloqueada(request.method, request.host, None if da_extensao else request.headers.get("Origin"), ORIGENS)
    if motivo:
        return jsonify({"error": motivo}), 403

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
    """Histórico de coletas. Filtros opcionais: de, ate (AAAA-MM-DD), loja, produto_id, status."""
    try:
        with db_fabrica() as s:
            return jsonify(relatorios.historico(
                s, de=request.args.get("de"), ate=request.args.get("ate"), loja=request.args.get("loja"),
                produto_id=request.args.get("produto_id", type=int), status=request.args.get("status"),
            ))
    except ValueError:
        return jsonify({"error": "Datas devem estar no formato AAAA-MM-DD"}), 400

@app.route("/api/historico/exportar", methods=["POST"])
def exportar_historico():
    """Excel das coletas pedidas (ids), com preços numéricos e o caminho do print."""
    data = request.get_json(force=True, silent=True) or {}
    ids = [int(i) for i in data.get("ids", []) if str(i).isdigit()]
    try:
        with db_fabrica() as s:
            conteudo = relatorios.exportar_excel(s, ids)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    nome = f"relatorio_{datetime.now():%Y%m%d_%H%M}.xlsx"
    return send_file(
        BytesIO(conteudo), as_attachment=True, download_name=nome,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

@app.route("/api/prints-galeria", methods=["GET"])
def galeria_de_prints():
    """Prints ligados às coletas, com o preço da hora. Sem parâmetros devolve as datas disponíveis."""
    data, produto_id = request.args.get("data"), request.args.get("produto_id", type=int)
    try:
        with db_fabrica() as s:
            if not data and not produto_id:
                return jsonify({"datas": relatorios.datas_com_prints(s)})
            return jsonify({"itens": relatorios.galeria(s, data=data, produto_id=produto_id)})
    except ValueError:
        return jsonify({"error": "Data deve estar no formato AAAA-MM-DD"}), 400

@app.route("/api/saude", methods=["GET"])
def painel_de_saude():
    with db_fabrica() as s:
        return jsonify(relatorios.saude(s))


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

# ==============================
# Rotas: ALERTAS DE PREÇO POR E-MAIL
# ==============================
def _alerta_json(a, p):
    return {
        "id": a.id, "produto_id": p.id, "produto": p.nome_comercial, "loja": p.loja,
        "preco_anterior": formatar_brl(a.preco_anterior_centavos), "preco_atual": formatar_brl(a.preco_atual_centavos),
        "queda_pct": a.queda_pct, "base_preco": a.base_preco, "motivos": a.motivos,
        "enviado_em": a.enviado_em.isoformat(timespec="seconds"), "destinatario": a.destinatario,
        "sucesso": a.sucesso, "erro": a.erro,
    }

@app.route("/api/alertas", methods=["GET"])
def listar_alertas():
    with db_fabrica() as s:
        linhas = s.execute(
            select(Alerta, Produto).join(Produto, Alerta.produto_id == Produto.id).order_by(Alerta.id.desc()).limit(200)
        ).all()
        return jsonify({
            "smtp": alertas_email.status_config(),
            "config": alertas_config.ler_config(s),
            "alertas": [_alerta_json(a, p) for a, p in linhas],
        })

@app.route("/api/alertas/config", methods=["PUT"])
def salvar_config_alertas():
    data = request.get_json(force=True, silent=True) or {}
    with db_fabrica() as s:
        try:
            config = alertas_config.salvar_config(s, data)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        s.commit()
        return jsonify({"message": "Configuração de alertas salva.", "config": config})

def _regra_json(p):
    return {
        "produto_id": p.id, "nome": p.nome_comercial, "loja": p.loja,
        "alerta_pct": p.alerta_pct, "alerta_base": p.alerta_base,
        "alerta_preco_alvo": p.alerta_preco_alvo_centavos / 100 if p.alerta_preco_alvo_centavos is not None else None,
    }

@app.route("/api/alertas/regras", methods=["GET"])
def listar_regras_alerta():
    with db_fabrica() as s:
        return jsonify([_regra_json(p) for p in repo_links.listar_ativos(s)])

@app.route("/api/alertas/regras/<int:produto_id>", methods=["PUT"])
def salvar_regra_alerta(produto_id):
    """Regra própria do produto; campo vazio/null volta a usar o padrão global."""
    data = request.get_json(force=True, silent=True) or {}
    with db_fabrica() as s:
        p = s.get(Produto, produto_id)
        if p is None:
            return jsonify({"error": "Produto não encontrado"}), 404
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

@app.route("/api/alertas/teste", methods=["POST"])
def enviar_email_de_teste():
    ok, mensagem = alertas_servico.enviar_teste()
    return jsonify({"ok": ok, "message": mensagem}), (200 if ok else 500)

# ==============================
# Rotas: COLETA ASSISTIDA (fila + extensão do Chrome)
# ==============================
def _assistida(acao):
    """Executa uma ação da coleta assistida dentro de uma sessão do banco, traduzindo erros de validação em 400."""
    try:
        with db_fabrica() as s:
            return jsonify(acao(s))
    except (assistida.SessaoInvalida, ValueError, TypeError) as e:
        return jsonify({"error": str(e)}), 400

@app.route("/api/assistida/token", methods=["GET"])
def assistida_token():
    """Segredo que a página entrega à extensão no pareamento (a resposta não é legível por outros sites: sem CORS)."""
    return jsonify({"token": assistida.obter_token(), "servidor": f"http://127.0.0.1:{CONFIG_SERVIDOR.porta}"})

@app.route("/api/assistida/sessao", methods=["GET"])
def assistida_sessao():
    return _assistida(assistida.sessao)

@app.route("/api/assistida/iniciar", methods=["POST"])
def assistida_iniciar():
    data = request.get_json(force=True, silent=True) or {}
    return _assistida(lambda s: assistida.iniciar(s, data.get("stores"), data.get("include"), data.get("exclude")))

@app.route("/api/assistida/captura", methods=["POST"])
def assistida_captura():
    if not assistida.token_valido(request.headers.get("X-Searching-Token")):
        return jsonify({"error": "Token da extensão ausente ou inválido. Abra a tela Coleta assistida para parear."}), 401
    d = request.get_json(force=True, silent=True) or {}
    return _assistida(lambda s: assistida.registrar_captura(s, int(d.get("execucao_id", 0)), int(d.get("produto_id", 0)), d))

@app.route("/api/assistida/link-quebrado", methods=["POST"])
def assistida_link_quebrado():
    d = request.get_json(force=True, silent=True) or {}
    return _assistida(lambda s: assistida.registrar_link_quebrado(s, int(d.get("execucao_id", 0)), int(d.get("produto_id", 0))))

@app.route("/api/assistida/pular", methods=["POST"])
def assistida_pular():
    d = request.get_json(force=True, silent=True) or {}
    return _assistida(lambda s: assistida.pular(s, int(d.get("execucao_id", 0)), int(d.get("produto_id", 0))))

@app.route("/api/assistida/encerrar", methods=["POST"])
def assistida_encerrar():
    d = request.get_json(force=True, silent=True) or {}
    return _assistida(lambda s: assistida.encerrar(s, int(d.get("execucao_id", 0)), notificador=alertas_servico.Notificador()))

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
    if CONFIG_SERVIDOR.aviso:
        print(f"   ⚠️  {CONFIG_SERVIDOR.aviso}")
    app.run(host=CONFIG_SERVIDOR.host, port=CONFIG_SERVIDOR.porta, debug=CONFIG_SERVIDOR.debug)
