"""Servidor da API. Aqui ficam só a montagem (configuração, proteções e registro dos blueprints) e o início.

As rotas estão em `searching/web/`, uma por assunto: contas, links/revisões, relatórios, alertas, coleta assistida e sistema.
A política de acesso de cada rota fica em `searching/auth/politicas.py` (deny by default).
"""
import logging
import os
import subprocess  # noqa: F401  (os testes trocam server.subprocess.run)
import sys

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from sqlalchemy import select

from searching import assistida, logs, modo, seguranca  # noqa: F401
from searching.alerts import email as alertas_email  # noqa: F401  (reexportado: os testes o trocam por aqui)
from searching.alerts import servico as alertas_servico
from searching.auth import guarda
from searching.db.session import PRINTS_DIR as prints_dir_config
from searching.db.session import criar_engine, iniciar_banco
from searching.web import (
    rotas_alertas,
    rotas_assistida,
    rotas_conta,
    rotas_links,
    rotas_relatorios,
    rotas_sistema,
)
from searching.web.coleta_cli import rodar_coleta_cli  # noqa: F401

BASE_DIR = os.path.dirname(__file__)
PRINTS_DIR = str(prints_dir_config)
os.makedirs(PRINTS_DIR, exist_ok=True)

db_fabrica = iniciar_banco(criar_engine())

# Os prints do servidor têm emoji; com a saída redirecionada (cp1252) isso derrubava o servidor.
for _fluxo in (sys.stdout, sys.stderr):
    if hasattr(_fluxo, "reconfigure"):
        _fluxo.reconfigure(encoding="utf-8", errors="replace")

CONFIG_SERVIDOR = seguranca.configuracao_servidor()
ORIGENS = seguranca.origens_permitidas(porta=CONFIG_SERVIDOR.porta)
HOSPEDADO = modo.hospedado()
FRONTEND_DIST = os.path.join(os.path.dirname(BASE_DIR), "frontend", "dist")

app = Flask(__name__, static_folder=None)
CORS(app, origins=sorted(ORIGENS), supports_credentials=HOSPEDADO)  # só o nosso frontend; nada de "*"
app.config["MAX_CONTENT_LENGTH"] = 40 * 1024 * 1024  # a captura traz o HTML da página e o print
app.config["DB_FABRICA"] = db_fabrica
app.config["ORIGENS"] = ORIGENS
app.config["PRINTS_DIR"] = PRINTS_DIR
app.config["PORTA"] = CONFIG_SERVIDOR.porta
app.config["NOTIFICADOR"] = alertas_servico.Notificador()
if HOSPEDADO and os.environ.get("SEARCHING_PROXIES"):  # atrás de um proxy reverso confiável (nginx, Caddy, nuvem)
    from werkzeug.middleware.proxy_fix import ProxyFix

    n = int(os.environ["SEARCHING_PROXIES"])
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=n, x_proto=n, x_host=n)

if HOSPEDADO or os.environ.get("SEARCHING_LOG_FORMATO"):  # logs estruturados (uma linha JSON por requisição)
    logs.configurar()
    logs.instalar(app)


# Ordem de execução de cada requisição: filtro de Host/Origin (abaixo) -> política de acesso (guarda.instalar).
@app.before_request
def proteger_servidor_local():
    """Recusa Host de fora (DNS rebinding) e escritas vindas de sites que não são o nosso frontend (CSRF)."""
    # A extensão envia as capturas com Origin "chrome-extension://..." e prova quem é pelo token (por usuário no
    # modo hospedado, arquivo local no modo local). Token no cabeçalho não é credencial "ambiente": outro site não o envia.
    if request.path == "/api/health":  # verificação de saúde do orquestrador (Host interno); não expõe dado nenhum
        return None
    if HOSPEDADO:
        da_extensao = bool(guarda.token_da_requisicao())
    else:
        da_extensao = request.path in ("/api/assistida/captura", "/api/assistida/autorizar") and assistida.token_valido(
            request.headers.get("X-Searching-Token")
        )
    motivo = seguranca.requisicao_bloqueada(request.method, request.host, None if da_extensao else request.headers.get("Origin"), ORIGENS)
    if motivo:
        return jsonify({"error": motivo}), 403


guarda.instalar(app)
for _bp in (
    rotas_conta.bp, rotas_links.bp, rotas_relatorios.bp, rotas_alertas.bp, rotas_assistida.bp, rotas_sistema.bp,
):
    app.register_blueprint(_bp)


# O site (frontend/dist) só é servido pelo Flask no modo hospedado: mesma origem da API, cookie de sessão sem CORS.
if HOSPEDADO:
    @app.route("/", defaults={"caminho": ""}, endpoint="arquivos_do_site_raiz")
    @app.route("/<path:caminho>", endpoint="arquivos_do_site")
    def arquivos_do_site(caminho):
        if caminho.startswith("api/"):
            return jsonify({"error": "Rota não encontrada"}), 404
        alvo = os.path.join(FRONTEND_DIST, caminho)
        if caminho and os.path.isfile(alvo):
            return send_from_directory(FRONTEND_DIST, caminho)
        return send_from_directory(FRONTEND_DIST, "index.html")

    from searching import retencao as _retencao
    from searching.db.models import Usuario

    with db_fabrica() as _s:  # aplica a política de retenção dos prints a cada início (e por cron: searching.operacao reter-prints)
        _r = _retencao.aplicar(_s)
        if _r["removidos"] or _r["arquivados"]:
            logging.getLogger("searching").info("retenção de prints aplicada", extra=_r)

    with db_fabrica() as _s:
        if not _s.scalar(select(Usuario.id).limit(1)):
            logging.getLogger("searching").warning(
                "Nenhum usuário cadastrado: crie o primeiro administrador com  python -m searching.usuarios criar-admin --email voce@exemplo.com"
            )


if __name__ == "__main__":
    if HOSPEDADO and not os.environ.get("SEARCHING_PERMITIR_DEV"):  # SEARCHING_PERMITIR_DEV=1 só para o teste e2e local
        sys.exit("O modo hospedado não usa o servidor de desenvolvimento do Flask. Use: gunicorn -b 0.0.0.0:8000 server:app (veja docs/IMPLANTACAO.md).")
    print("===========================================")
    print("   🚀 Servidor Flask iniciado com sucesso! ")
    print("   📄 Dados no banco local (backend/data/searching.db)")
    print("===========================================")
    if CONFIG_SERVIDOR.aviso:
        print(f"   ⚠️  {CONFIG_SERVIDOR.aviso}")
    app.run(host=CONFIG_SERVIDOR.host, port=CONFIG_SERVIDOR.porta, debug=CONFIG_SERVIDOR.debug)
