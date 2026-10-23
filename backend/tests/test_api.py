import importlib
import sys

import pytest

from searching.db.models import Coleta, RevisaoLink
from datetime import datetime


@pytest.fixture
def api(tmp_path, monkeypatch):
    """Cliente Flask apontando para um banco temporário (o server cria o banco ao ser importado)."""
    monkeypatch.setenv("SEARCHING_DB", str(tmp_path / "api.db"))
    sys.modules.pop("server", None)
    server = importlib.import_module("server")
    yield server.app.test_client(), server
    sys.modules.pop("server", None)


def _criar(c, nome="Samsung Galaxy S25 256GB", link="https://www.magazineluiza.com.br/a/p/1/"):
    r = c.post("/api/links", json={"nome": nome, "link": link})
    assert r.status_code == 200
    return r.get_json()["id"]


def test_crud_de_links_por_id(api):
    c, _ = api
    pid = _criar(c)
    lista = c.get("/api/links").get_json()
    assert lista == [{"ID": pid, "NOME COMERCIAL": "Samsung Galaxy S25 256GB", "LINK": "https://www.magazineluiza.com.br/a/p/1/", "LOJA": "Magazine Luiza"}]

    assert c.post("/api/links", json={"nome": "", "link": "https://x/p/2/"}).status_code == 400
    dup = c.post("/api/links", json={"nome": "Samsung Galaxy S25 256GB", "link": "https://www.magazineluiza.com.br/b/p/2/"})
    assert dup.status_code == 409

    r = c.put("/api/links", json={"id": pid, "nome": "Samsung Galaxy S25 256GB", "link": "https://www.magazineluiza.com.br/novo/p/9/"})
    assert r.status_code == 200
    assert c.get("/api/links").get_json()[0]["LINK"].endswith("/novo/p/9/")

    # compatibilidade: telas antigas identificam por nome + link original
    r = c.put("/api/links", json={"originalNome": "Samsung Galaxy S25 256GB", "originalLink": "https://www.magazineluiza.com.br/novo/p/9/",
                                  "nome": "Samsung Galaxy S25 256GB", "link": "https://www.magazineluiza.com.br/outro/p/3/"})
    assert r.status_code == 200

    assert c.delete("/api/links", json={"id": pid}).status_code == 200
    assert c.get("/api/links").get_json() == []
    assert c.put("/api/links", json={"id": 999, "link": "https://x"}).status_code == 404


def test_historico_de_links_e_reversao(api):
    c, _ = api
    pid = _criar(c)
    c.put("/api/links", json={"id": pid, "link": "https://www.magazineluiza.com.br/novo/p/9/"})
    hist = c.get(f"/api/links/historico?produto_id={pid}").get_json()
    assert len(hist) == 1 and hist[0]["origem"] == "manual" and hist[0]["revertivel"]

    assert c.post(f"/api/links/historico/{hist[0]['id']}/reverter").status_code == 200
    assert c.get("/api/links").get_json()[0]["LINK"] == "https://www.magazineluiza.com.br/a/p/1/"
    assert c.post(f"/api/links/historico/{hist[0]['id']}/reverter").status_code == 409  # já não é o link atual
    assert c.post("/api/links/historico/999/reverter").status_code == 404


def test_fila_de_revisao(api):
    c, server = api
    pid = _criar(c)
    with server.db_fabrica() as s:
        s.add(Coleta(produto_id=pid, coletado_em=datetime.now(), status="LINK_QUEBRADO", erro_detalhe="página não encontrada",
                     caminho_print="prints/2026-10-23/S25_12-00-00.png"))
        s.add(RevisaoLink(produto_id=pid, motivo="LINK_QUEBRADO",
                          candidatos=[{"url": "https://www.magazineluiza.com.br/n/p/7/", "titulo": "Samsung Galaxy S25 5G, 256GB", "nota": 0.9, "estrategia": "busca", "verificado": False}]))
        s.commit()

    itens = c.get("/api/revisoes").get_json()
    assert len(itens) == 1
    r = itens[0]
    assert r["produto"]["id"] == pid and r["motivo"] == "LINK_QUEBRADO" and r["candidatos"][0]["nota"] == 0.9
    assert r["ultima_coleta"]["print_url"] == "/api/prints/2026-10-23/S25_12-00-00.png"

    assert c.post(f"/api/revisoes/{r['id']}/resolver", json={"acao": "aprovar"}).status_code == 400  # falta o link
    assert c.post(f"/api/revisoes/{r['id']}/resolver", json={"acao": "aprovar", "url": "https://www.magazineluiza.com.br/n/p/7/"}).status_code == 200
    assert c.get("/api/revisoes").get_json() == []
    assert c.get("/api/links").get_json()[0]["LINK"].endswith("/n/p/7/")
    assert c.get("/api/revisoes?estado=aprovado").get_json()[0]["id"] == r["id"]
    assert c.post(f"/api/revisoes/{r['id']}/resolver", json={"acao": "desativar"}).status_code == 400  # já resolvida
    assert c.post("/api/revisoes/999/resolver", json={"acao": "desativar"}).status_code == 404


def test_historico_de_coletas_traz_o_id_do_produto(api):
    c, server = api
    pid = _criar(c)
    with server.db_fabrica() as s:
        s.add(Coleta(produto_id=pid, coletado_em=datetime(2026, 10, 23, 12, 0), status="OK", preco_pix_centavos=379900))
        s.commit()
    linha = c.get("/api/historico").get_json()[0]
    assert linha["PRODUTO_ID"] == pid and linha["PIX"] == "R$ 3.799,00" and linha["LINK"].endswith("/a/p/1/")
