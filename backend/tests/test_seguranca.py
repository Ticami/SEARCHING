import importlib
import sys
from types import SimpleNamespace

import pytest

from searching import seguranca

LOCAL = seguranca.origens_permitidas({})


# ---------- funções puras ----------
def test_servidor_so_escuta_em_loopback_e_sem_debug_por_padrao():
    c = seguranca.configuracao_servidor({})
    assert (c.host, c.porta, c.debug, c.aviso) == ("127.0.0.1", 5000, False, None)


@pytest.mark.parametrize("pedido", ["0.0.0.0", "192.168.0.10", "::", "meu-pc"])
def test_host_fora_do_loopback_e_ignorado_com_aviso(pedido):
    c = seguranca.configuracao_servidor({"SEARCHING_HOST": pedido})
    assert c.host == "127.0.0.1" and "ignorado" in c.aviso


def test_porta_e_debug_so_mudam_por_variavel_de_ambiente():
    c = seguranca.configuracao_servidor({"SEARCHING_PORT": "5055", "SEARCHING_DEBUG": "1", "SEARCHING_HOST": "localhost"})
    assert (c.host, c.porta, c.debug) == ("localhost", 5055, True)
    assert seguranca.configuracao_servidor({"SEARCHING_PORT": "abc"}).porta == 5000


def test_origens_permitidas_sao_so_locais():
    assert "http://localhost:5173" in LOCAL and "http://127.0.0.1:5173" in LOCAL and "http://127.0.0.1:5000" in LOCAL
    assert not any("evil" in o or "0.0.0.0" in o for o in LOCAL)
    extra = seguranca.origens_permitidas({"SEARCHING_ORIGENS": "http://localhost:3000/, https://evil.com, http://192.168.0.5:5173"})
    assert "http://localhost:3000" in extra and "https://evil.com" not in extra and "http://192.168.0.5:5173" not in extra


@pytest.mark.parametrize("host, esperado", [
    ("127.0.0.1:5000", True), ("localhost:5173", True), ("localhost", True), ("[::1]:5000", True),
    ("evil.com", False), ("evil.com:5000", False), ("127.0.0.1.evil.com", False), ("192.168.0.10:5000", False), ("", False), (None, False),
])
def test_host_permitido(host, esperado):
    assert seguranca.host_permitido(host) is esperado


@pytest.mark.parametrize("metodo, host, origem, bloqueada", [
    ("GET", "127.0.0.1:5000", None, False),
    ("GET", "evil.com", None, True),                                   # DNS rebinding
    ("POST", "127.0.0.1:5000", "http://localhost:5173", False),        # nosso frontend
    ("POST", "127.0.0.1:5000", None, False),                           # curl, CLI, testes (sem Origin)
    ("POST", "127.0.0.1:5000", "https://evil.com", True),              # site externo (CSRF)
    ("DELETE", "127.0.0.1:5000", "null", True),                        # página local/sandbox: Origin "null"
    ("PUT", "127.0.0.1:5000", "http://localhost:6666", True),          # outra porta local não autorizada
    ("OPTIONS", "127.0.0.1:5000", "https://evil.com", False),          # preflight: o CORS responde sem liberar
])
def test_requisicao_bloqueada(metodo, host, origem, bloqueada):
    assert (seguranca.requisicao_bloqueada(metodo, host, origem, LOCAL) is not None) is bloqueada


# ---------- servidor de verdade ----------
@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("SEARCHING_DB", str(tmp_path / "seg.db"))
    sys.modules.pop("server", None)
    server = importlib.import_module("server")
    yield server.app.test_client(), server
    sys.modules.pop("server", None)


def test_host_de_fora_recebe_403(api):
    c, _ = api
    assert c.get("/api/links", base_url="http://evil.com").status_code == 403
    assert c.get("/api/links", base_url="http://127.0.0.1:5000").status_code == 200
    assert c.get("/api/links", base_url="http://localhost:5000").status_code == 200


def test_post_de_site_externo_nao_cria_nada_mesmo_como_text_plain(api):
    c, server = api
    corpo = '{"nome": "Produto Falso", "link": "https://www.magazineluiza.com.br/x/p/1/"}'
    # "requisição simples" de outro site: sem preflight, Content-Type text/plain (o servidor aceita JSON forçado)
    r = c.post("/api/links", data=corpo, headers={"Origin": "https://evil.com", "Content-Type": "text/plain"})
    assert r.status_code == 403
    assert c.get("/api/links").get_json() == []
    r = c.post("/api/links", data=corpo, headers={"Origin": "http://localhost:5173", "Content-Type": "application/json"})
    assert r.status_code == 200 and len(c.get("/api/links").get_json()) == 1


@pytest.mark.parametrize("rota, metodo", [("/api/coletar", "post"), ("/api/alertas/teste", "post"), ("/api/schedule", "post"),
                                           ("/api/links", "delete"), ("/api/alertas/config", "put")])
def test_nenhuma_rota_de_escrita_aceita_origem_externa(api, rota, metodo):
    c, _ = api
    r = getattr(c, metodo)(rota, json={}, headers={"Origin": "https://evil.com"})
    assert r.status_code == 403


def test_cors_so_libera_o_frontend_local(api):
    c, _ = api
    ok = c.get("/api/links", headers={"Origin": "http://localhost:5173"})
    assert ok.headers.get("Access-Control-Allow-Origin") == "http://localhost:5173"
    fora = c.get("/api/links", headers={"Origin": "https://evil.com"})
    assert fora.headers.get("Access-Control-Allow-Origin") is None
    assert c.get("/api/links", headers={"Origin": "http://localhost:5173"}).headers.get("Access-Control-Allow-Origin") != "*"


def test_filtros_do_coletor_nao_viram_opcoes_da_linha_de_comando(api, monkeypatch):
    _, server = api
    capturado = {}

    def falso_run(cmd, **kw):
        capturado["cmd"] = cmd
        return SimpleNamespace(returncode=0, stdout='{"ok": 1}', stderr="")

    monkeypatch.setattr(server.subprocess, "run", falso_run)
    server.rodar_coleta_cli("manual", stores=["--origem=agendada"], include=["--log-nivel", "x y"], exclude=["a; calc.exe"])
    cmd = capturado["cmd"]
    assert "--loja=--origem=agendada" in cmd and "--incluir=--log-nivel" in cmd and "--excluir=a; calc.exe" in cmd
    assert not any(a in cmd for a in ("--origem=agendada", "--log-nivel"))  # nenhum filtro virou opção solta
    assert cmd.count("--origem") == 1 and not any(isinstance(a, str) and a == "shell" for a in cmd)
