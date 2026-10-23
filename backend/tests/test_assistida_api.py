import base64
import importlib
import sys
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
URL_S25 = "https://www.magazineluiza.com.br/celular-samsung-galaxy-s25/p/abc123/te/gs25/"
PNG = "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"x" * 40).decode()
EXTENSAO = "chrome-extension://abcdefghijklmnopabcdefghijklmnop"


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("SEARCHING_DB", str(tmp_path / "a.db"))
    monkeypatch.setenv("SEARCHING_PRINTS", str(tmp_path / "prints"))
    sys.modules.pop("server", None)
    server = importlib.import_module("server")
    monkeypatch.setattr(server.assistida, "TOKEN_PATH", tmp_path / "assistida.token")
    yield server.app.test_client(), server
    sys.modules.pop("server", None)


def _produto(c):
    return c.post("/api/links", json={"nome": "Samsung Galaxy S25 256GB", "link": URL_S25}).get_json()["id"]


def _corpo(execucao_id, produto_id, **kw):
    base = {"execucao_id": execucao_id, "produto_id": produto_id, "url_final": URL_S25, "screenshot": PNG,
            "html": (FIXTURES / "magalu_produto.html").read_text(encoding="utf-8"),
            "html_modal": (FIXTURES / "magalu_modal_pagamento.html").read_text(encoding="utf-8")}
    base.update(kw)
    return base


def test_fluxo_completo_pela_api(api):
    c, server = api
    pid = _produto(c)
    token = c.get("/api/assistida/token").get_json()["token"]
    assert c.get("/api/assistida/sessao").get_json() == {"ativa": False}

    sess = c.post("/api/assistida/iniciar", json={}).get_json()
    assert sess["ativa"] and sess["total"] == 1 and sess["proximo_produto_id"] == pid

    # a extensão envia a captura: Origin da extensão + token
    r = c.post("/api/assistida/captura", json=_corpo(sess["execucao_id"], pid), headers={"Origin": EXTENSAO, "X-Searching-Token": token})
    assert r.status_code == 200, r.get_json()
    cap = r.get_json()
    assert (cap["status"], cap["pix"], cap["cartao_1x"]) == ("OK", "R$ 3.799,00", "R$ 3.998,95")
    assert cap["print_url"] and (Path(server.prints_dir_config) / cap["print_url"].split("/api/prints/")[1]).exists()

    depois = c.get("/api/assistida/sessao").get_json()
    assert depois["concluidos"] == 1 and depois["proximo_produto_id"] is None

    fim = c.post("/api/assistida/encerrar", json={"execucao_id": sess["execucao_id"]}).get_json()
    assert (fim["ok"], fim["falhas"], fim["coletados"]) == (1, 0, 1)
    assert c.get("/api/assistida/sessao").get_json() == {"ativa": False}
    # a coleta aparece nos relatórios como qualquer outra
    assert c.get("/api/historico").get_json()[0]["PIX_CENTAVOS"] == 379900


def test_captura_exige_o_token_certo(api):
    c, _ = api
    pid = _produto(c)
    sess = c.post("/api/assistida/iniciar", json={}).get_json()
    corpo = _corpo(sess["execucao_id"], pid)
    token = c.get("/api/assistida/token").get_json()["token"]

    sem = c.post("/api/assistida/captura", json=corpo)  # sem Origin (curl): passa a checagem de origem, cai no token
    assert sem.status_code == 401
    errado = c.post("/api/assistida/captura", json=corpo, headers={"X-Searching-Token": "errado"})
    assert errado.status_code == 401
    # Origin de extensão com token errado: a checagem de origem barra antes
    assert c.post("/api/assistida/captura", json=corpo, headers={"Origin": EXTENSAO, "X-Searching-Token": "errado"}).status_code == 403
    assert c.get("/api/assistida/sessao").get_json()["concluidos"] == 0
    ok = c.post("/api/assistida/captura", json=corpo, headers={"X-Searching-Token": token})
    assert ok.status_code == 200


def test_site_externo_nao_mexe_na_fila_nem_com_o_token_dos_outros_endpoints(api):
    c, _ = api
    pid = _produto(c)
    sess = c.post("/api/assistida/iniciar", json={}).get_json()
    ex = sess["execucao_id"]
    mau = {"Origin": "https://evil.com"}
    for rota, corpo in [("/api/assistida/iniciar", {}), ("/api/assistida/pular", {"execucao_id": ex, "produto_id": pid}),
                        ("/api/assistida/link-quebrado", {"execucao_id": ex, "produto_id": pid}), ("/api/assistida/encerrar", {"execucao_id": ex})]:
        assert c.post(rota, json=corpo, headers=mau).status_code == 403, rota
    # mesmo uma página maliciosa que soubesse o token só vale em /captura, e lá a origem de fora também é recusada sem o token
    assert c.post("/api/assistida/captura", json=_corpo(ex, pid), headers={"Origin": "https://evil.com"}).status_code == 403
    assert c.get("/api/assistida/token", headers=mau).headers.get("Access-Control-Allow-Origin") is None  # o token não é legível por outros sites
    assert c.get("/api/assistida/sessao").get_json()["concluidos"] == 0


def test_erros_viram_400_com_mensagem(api):
    c, _ = api
    assert c.post("/api/assistida/iniciar", json={}).status_code == 400  # nenhum produto cadastrado
    pid = _produto(c)
    sess = c.post("/api/assistida/iniciar", json={}).get_json()
    token = c.get("/api/assistida/token").get_json()["token"]
    h = {"X-Searching-Token": token}
    assert c.post("/api/assistida/captura", json=_corpo(999, pid), headers=h).status_code == 400
    assert c.post("/api/assistida/captura", json=_corpo(sess["execucao_id"], pid, html=""), headers=h).status_code == 400
    assert c.post("/api/assistida/captura", json={"execucao_id": "abc", "produto_id": pid}, headers=h).status_code == 400
    assert c.post("/api/assistida/pular", json={"execucao_id": sess["execucao_id"], "produto_id": 12345}).status_code == 400


def test_pular_e_link_quebrado_pela_api(api):
    c, _ = api
    pid = _produto(c)
    ex = c.post("/api/assistida/iniciar", json={}).get_json()["execucao_id"]
    r = c.post("/api/assistida/link-quebrado", json={"execucao_id": ex, "produto_id": pid})
    assert r.status_code == 200 and r.get_json()["status"] == "LINK_QUEBRADO"
    assert len(c.get("/api/revisoes").get_json()) == 1  # cai na fila de Revisão de links
