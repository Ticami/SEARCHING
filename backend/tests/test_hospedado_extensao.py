"""Modo hospedado + extensão: token por usuário, revogação imediata, intervalo e limite impostos pelo servidor,
coordenação entre pessoas e a garantia de que o servidor nunca acessa lojas."""
import base64
from datetime import datetime, timedelta

import pytest
from conftest import EXTENSAO, FIXTURES, URL_S25
from sqlalchemy import select

from searching import modo
from searching.db.models import AberturaPagina, Coleta, Configuracao

PNG = "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"x" * 40).decode()
URL_OUTRO = "https://www.magazineluiza.com.br/celular-motorola-edge/p/zzz111/te/edge/"


def _corpo(execucao_id, produto_id, **kw):
    base = {"execucao_id": execucao_id, "produto_id": produto_id, "url_final": URL_S25, "screenshot": PNG,
            "html": (FIXTURES / "magalu_produto.html").read_text(encoding="utf-8"),
            "html_modal": (FIXTURES / "magalu_modal_pagamento.html").read_text(encoding="utf-8")}
    base.update(kw)
    return base


def _ext(hosp, token, rota, corpo, origem=EXTENSAO):
    """Requisição da extensão: sem cookie, Origin chrome-extension://..., token no cabeçalho."""
    c = hosp.server.app.test_client()
    return c.post(rota, json=corpo, headers={"Origin": origem, "X-Searching-Token": token}, base_url="https://searching.teste")


def _preparar(hosp, quem=("coletor@teste.com",)):
    """Admin cadastra o produto e o atribui; devolve (produto_id, {email: cliente})."""
    adm = hosp.cliente("admin@teste.com")
    pid = adm.post("/api/links", {"nome": "Samsung Galaxy S25 256GB", "link": URL_S25}).get_json()["id"]
    clientes = {}
    for email in quem:
        adm.put(f"/api/atribuicoes/{hosp.uid(email)}", {"produtos": [pid]})
        clientes[email] = hosp.cliente(email)
    return pid, adm, clientes


def _parear(cliente):
    r = cliente.post("/api/extensao/parear")
    assert r.status_code == 200, r.get_json()
    return r.get_json()["token"]


def _liberar_intervalo(hosp):
    with hosp.fabrica() as s:
        for a in s.scalars(select(AberturaPagina)):
            a.em = a.em - timedelta(minutes=1)
        s.commit()


# ---------- pareamento e escopo ----------
def test_pareamento_cria_token_do_usuario_e_so_coletor_pareia(hosp):
    _, _, cl = _preparar(hosp)
    r = cl["coletor@teste.com"].post("/api/extensao/parear")
    assert r.status_code == 200 and r.get_json()["token"].startswith("sch_e_") and r.get_json()["servidor"] == "https://searching.teste"
    assert hosp.cliente("leitor@teste.com").post("/api/extensao/parear").status_code == 403
    assert hosp.cliente("leitor@teste.com").post("/api/meus-tokens", {"tipo": "extensao"}).status_code == 403


def test_pareamento_de_novo_revoga_o_anterior_da_tela(hosp):
    _, _, cl = _preparar(hosp)
    c = cl["coletor@teste.com"]
    velho, novo = _parear(c), _parear(c)
    assert _ext(hosp, velho, "/api/assistida/autorizar", {}).status_code == 401
    assert _ext(hosp, novo, "/api/assistida/autorizar", {}).status_code == 400  # token ok; falta sessão aberta


def test_token_so_guarda_o_hash(hosp):
    _, _, cl = _preparar(hosp)
    token = _parear(cl["coletor@teste.com"])
    from searching.db.models import TokenApi

    with hosp.fabrica() as s:
        t = s.scalar(select(TokenApi))
        assert token not in (t.hash, t.prefixo) and len(t.hash) == 64 and token.startswith(t.prefixo)


def test_usuario_a_nao_usa_o_token_do_usuario_b(hosp):
    pid, _, cl = _preparar(hosp, ("coletor@teste.com", "coletor2@teste.com"))
    a, b = cl["coletor@teste.com"], cl["coletor2@teste.com"]
    token_a, token_b = _parear(a), _parear(b)
    sess_a = a.post("/api/assistida/iniciar", {}).get_json()
    assert sess_a["ativa"]

    # B tenta capturar/autorizar na execução de A, com o PRÓPRIO token: a sessão é de A, então não existe para B
    r = _ext(hosp, token_b, "/api/assistida/captura", _corpo(sess_a["execucao_id"], pid))
    assert r.status_code == 400 and "não está aberta" in r.get_json()["error"]
    assert _ext(hosp, token_b, "/api/assistida/autorizar", {"execucao_id": sess_a["execucao_id"], "produto_id": pid}).status_code == 400
    with hosp.fabrica() as s:
        assert s.scalar(select(Coleta.id)) is None
    # B também não encerra nem pula a execução de A pela tela
    assert b.post("/api/assistida/encerrar", {"execucao_id": sess_a["execucao_id"]}).status_code == 400
    assert b.post("/api/assistida/pular", {"execucao_id": sess_a["execucao_id"], "produto_id": pid}).status_code == 400
    # o token de A funciona na sessão de A
    assert _ext(hosp, token_a, "/api/assistida/autorizar", {"execucao_id": sess_a["execucao_id"], "produto_id": pid}).status_code == 200


def test_captura_registra_quem_capturou(hosp):
    pid, _, cl = _preparar(hosp)
    c = cl["coletor@teste.com"]
    token = _parear(c)
    sess = c.post("/api/assistida/iniciar", {}).get_json()
    assert _ext(hosp, token, "/api/assistida/autorizar", {"execucao_id": sess["execucao_id"], "produto_id": pid}).status_code == 200
    r = _ext(hosp, token, "/api/assistida/captura", _corpo(sess["execucao_id"], pid))
    assert r.status_code == 200 and r.get_json()["status"] == "OK" and r.get_json()["pix"] == "R$ 3.799,00"
    with hosp.fabrica() as s:
        coleta = s.scalar(select(Coleta))
        assert coleta.coletado_por_id == hosp.uid("coletor@teste.com")
    assert c.post("/api/assistida/encerrar", {"execucao_id": sess["execucao_id"]}).status_code == 200


def test_token_da_extensao_nao_serve_para_mais_nada(hosp):
    _, _, cl = _preparar(hosp)
    token = cl["coletor@teste.com"].post("/api/extensao/parear").get_json()["token"]
    c = hosp.server.app.test_client()
    h = {"X-Searching-Token": token}
    assert c.get("/api/links", headers=h, base_url="https://searching.teste").status_code == 401
    assert c.post("/api/links", json={}, headers={**h, "Origin": EXTENSAO}, base_url="https://searching.teste").status_code == 401
    # sem token, a captura com Origin da extensão é barrada
    assert _ext(hosp, "sch_e_inventado", "/api/assistida/captura", {}).status_code == 401
    sem = hosp.server.app.test_client().post("/api/assistida/captura", json={}, headers={"Origin": EXTENSAO}, base_url="https://searching.teste")
    assert sem.status_code == 403


# ---------- revogação ----------
def test_token_revogado_para_de_funcionar_na_hora(hosp):
    pid, adm, cl = _preparar(hosp)
    c = cl["coletor@teste.com"]
    token = _parear(c)
    sess = c.post("/api/assistida/iniciar", {}).get_json()
    corpo = {"execucao_id": sess["execucao_id"], "produto_id": pid}
    assert _ext(hosp, token, "/api/assistida/autorizar", corpo).status_code == 200
    tid = c.get("/api/meus-tokens").get_json()[0]["id"]
    assert adm.delete(f"/api/tokens/{tid}").status_code == 200  # revogado pelo admin, na tela de Usuários
    _liberar_intervalo(hosp)
    assert _ext(hosp, token, "/api/assistida/autorizar", corpo).status_code == 401
    assert _ext(hosp, token, "/api/assistida/captura", _corpo(sess["execucao_id"], pid)).status_code == 401
    with hosp.fabrica() as s:
        assert s.scalar(select(Coleta.id)) is None


def test_usuario_revoga_o_proprio_token(hosp):
    _, _, cl = _preparar(hosp)
    c = cl["coletor@teste.com"]
    token = _parear(c)
    tid = c.get("/api/meus-tokens").get_json()[0]["id"]
    assert c.delete(f"/api/meus-tokens/{tid}").status_code == 200
    assert _ext(hosp, token, "/api/assistida/autorizar", {}).status_code == 401
    # e não revoga o de outra pessoa
    outro = hosp.cliente("coletor2@teste.com")
    _parear(outro)
    tid2 = outro.get("/api/meus-tokens").get_json()[0]["id"]
    assert c.delete(f"/api/meus-tokens/{tid2}").status_code == 404


def test_desativar_ou_rebaixar_usuario_derruba_o_token(hosp):
    _, adm, cl = _preparar(hosp, ("coletor@teste.com", "coletor2@teste.com"))
    t1, t2 = _parear(cl["coletor@teste.com"]), _parear(cl["coletor2@teste.com"])
    assert adm.patch(f"/api/usuarios/{hosp.uid('coletor@teste.com')}", {"ativo": False}).status_code == 200
    assert adm.patch(f"/api/usuarios/{hosp.uid('coletor2@teste.com')}", {"papel": "leitor"}).status_code == 200
    assert _ext(hosp, t1, "/api/assistida/autorizar", {}).status_code == 401
    assert _ext(hosp, t2, "/api/assistida/autorizar", {}).status_code == 401


# ---------- token de leitura (planilhas/BI) ----------
def test_token_de_leitura_so_le(hosp):
    leitor = hosp.cliente("leitor@teste.com")
    r = leitor.post("/api/meus-tokens", {"tipo": "leitura", "nome": "planilha"})
    assert r.status_code == 200
    token = r.get_json()["token"]
    c = hosp.server.app.test_client()
    h = {"Authorization": f"Bearer {token}"}
    base = "https://searching.teste"
    assert c.get("/api/links", headers=h, base_url=base).status_code == 200
    assert c.get("/api/historico", headers=h, base_url=base).status_code == 200
    assert c.get("/api/usuarios", headers=h, base_url=base).status_code == 403
    assert c.post("/api/links", json={}, headers=h, base_url=base).status_code == 403
    assert c.post("/api/assistida/captura", json={}, headers=h, base_url=base).status_code == 401  # só token de extensão
    leitor.delete(f"/api/meus-tokens/{r.get_json()['info']['id']}")
    assert c.get("/api/links", headers=h, base_url=base).status_code == 401


# ---------- intervalo e limite impostos pelo servidor ----------
def test_servidor_impoe_intervalo_minimo_de_3_segundos(hosp):
    pid, _, cl = _preparar(hosp)
    c = cl["coletor@teste.com"]
    token = _parear(c)
    sess = c.post("/api/assistida/iniciar", {}).get_json()
    corpo = {"execucao_id": sess["execucao_id"], "produto_id": pid}
    assert _ext(hosp, token, "/api/assistida/autorizar", corpo).status_code == 200
    r = _ext(hosp, token, "/api/assistida/autorizar", corpo)
    assert r.status_code == 429 and r.get_json()["aguardar_ms"] > 0
    _liberar_intervalo(hosp)
    assert _ext(hosp, token, "/api/assistida/autorizar", corpo).status_code == 200


def test_limite_global_por_loja_e_alerta_na_auditoria(hosp):
    pid, adm, cl = _preparar(hosp)
    c = cl["coletor@teste.com"]
    token = _parear(c)
    with hosp.fabrica() as s:
        s.merge(Configuracao(chave="limite_loja_hora", valor="2"))
        s.commit()
    sess = c.post("/api/assistida/iniciar", {}).get_json()
    corpo = {"execucao_id": sess["execucao_id"], "produto_id": pid}
    for _ in range(2):
        assert _ext(hosp, token, "/api/assistida/autorizar", corpo).status_code == 200
        _liberar_intervalo(hosp)
    r = _ext(hosp, token, "/api/assistida/autorizar", corpo)
    assert r.status_code == 429 and "Limite" in r.get_json()["error"]
    eventos = adm.get("/api/auditoria?acao=limite_loja").get_json()
    assert eventos and eventos[0]["detalhe"]["limite"] == 2 and eventos[0]["detalhe"]["aberturas_na_ultima_hora"] == 2


def test_limite_conta_todos_os_usuarios(hosp):
    adm = hosp.cliente("admin@teste.com")
    p1 = adm.post("/api/links", {"nome": "Samsung Galaxy S25 256GB", "link": URL_S25}).get_json()["id"]
    p2 = adm.post("/api/links", {"nome": "Motorola Edge 50 256GB", "link": URL_OUTRO}).get_json()["id"]
    adm.put(f"/api/atribuicoes/{hosp.uid('coletor@teste.com')}", {"produtos": [p1]})
    adm.put(f"/api/atribuicoes/{hosp.uid('coletor2@teste.com')}", {"produtos": [p2]})
    a, b = hosp.cliente("coletor@teste.com"), hosp.cliente("coletor2@teste.com")
    ta, tb = _parear(a), _parear(b)
    with hosp.fabrica() as s:
        s.merge(Configuracao(chave="limite_loja_hora", valor="1"))
        s.commit()
    sa, sb = a.post("/api/assistida/iniciar", {}).get_json(), b.post("/api/assistida/iniciar", {}).get_json()
    assert _ext(hosp, ta, "/api/assistida/autorizar", {"execucao_id": sa["execucao_id"], "produto_id": p1}).status_code == 200
    # a abertura de A já gastou o limite da loja: B (que nunca abriu nada) é barrado
    r = _ext(hosp, tb, "/api/assistida/autorizar", {"execucao_id": sb["execucao_id"], "produto_id": p2})
    assert r.status_code == 429 and "Limite" in r.get_json()["error"]


# ---------- coordenação entre pessoas ----------
def test_produto_em_coleta_por_uma_pessoa_nao_entra_na_fila_de_outra(hosp):
    pid, _, cl = _preparar(hosp, ("coletor@teste.com", "coletor2@teste.com"))
    a, b = cl["coletor@teste.com"], cl["coletor2@teste.com"]
    sa = a.post("/api/assistida/iniciar", {})
    assert sa.status_code == 200
    em = hosp.cliente("leitor@teste.com").get("/api/assistida/em-coleta").get_json()
    assert [(x["produto_id"], x["por"]) for x in em] == [(pid, "coletor")]
    rb = b.post("/api/assistida/iniciar", {})
    assert rb.status_code == 400 and "outra pessoa" in rb.get_json()["error"]
    # quando A encerra, B consegue
    assert a.post("/api/assistida/encerrar", {"execucao_id": sa.get_json()["execucao_id"]}).status_code == 200
    assert b.post("/api/assistida/iniciar", {}).status_code == 200


def test_fila_parcial_informa_o_que_ficou_de_fora(hosp):
    adm = hosp.cliente("admin@teste.com")
    p1 = adm.post("/api/links", {"nome": "Samsung Galaxy S25 256GB", "link": URL_S25}).get_json()["id"]
    p2 = adm.post("/api/links", {"nome": "Motorola Edge 50 256GB", "link": URL_OUTRO}).get_json()["id"]
    adm.put(f"/api/atribuicoes/{hosp.uid('coletor@teste.com')}", {"produtos": [p1]})
    adm.put(f"/api/atribuicoes/{hosp.uid('coletor2@teste.com')}", {"produtos": [p1, p2]})
    a, b = hosp.cliente("coletor@teste.com"), hosp.cliente("coletor2@teste.com")
    assert a.post("/api/assistida/iniciar", {}).status_code == 200
    sb = b.post("/api/assistida/iniciar", {}).get_json()
    assert [i["produto_id"] for i in sb["itens"]] == [p2]
    assert [(x["produto_id"], x["por"]) for x in sb["em_coleta_por_outros"]] == [(p1, "coletor")]


def test_coletor_so_coleta_o_que_lhe_foi_atribuido(hosp):
    adm = hosp.cliente("admin@teste.com")
    adm.post("/api/links", {"nome": "Samsung Galaxy S25 256GB", "link": URL_S25})
    c = hosp.cliente("coletor@teste.com")  # nada atribuído
    r = c.post("/api/assistida/iniciar", {})
    assert r.status_code == 400 and "atribuído" in r.get_json()["error"]
    assert adm.post("/api/assistida/iniciar", {}).status_code == 200  # admin coleta tudo


def test_sessoes_sao_independentes_por_usuario(hosp):
    pid, _, cl = _preparar(hosp, ("coletor@teste.com", "coletor2@teste.com"))
    a, b = cl["coletor@teste.com"], cl["coletor2@teste.com"]
    a.post("/api/assistida/iniciar", {})
    assert a.get("/api/assistida/sessao").get_json()["ativa"] is True
    assert b.get("/api/assistida/sessao").get_json() == {"ativa": False}


# ---------- o servidor hospedado nunca acessa lojas ----------
def test_servidor_hospedado_nao_faz_nenhuma_requisicao_a_lojas(hosp, monkeypatch):
    import socket
    import subprocess

    tentativas = []

    def sem_rede(self, endereco, *a, **k):
        tentativas.append(endereco)
        raise AssertionError(f"tentativa de conexão de rede: {endereco}")

    monkeypatch.setattr(socket.socket, "connect", sem_rede)
    monkeypatch.setattr(socket.socket, "connect_ex", sem_rede)
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: sem_rede(None, a[0]))
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: (_ for _ in ()).throw(AssertionError("subprocesso proibido")))
    monkeypatch.setattr(hosp.server.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("subprocesso proibido")))

    pid, adm, cl = _preparar(hosp)
    c = cl["coletor@teste.com"]
    token = _parear(c)
    # fluxo completo (cadastro, atribuição, pareamento, sessão, autorização, captura, encerramento) sem nenhuma conexão
    sess = c.post("/api/assistida/iniciar", {}).get_json()
    assert _ext(hosp, token, "/api/assistida/autorizar", {"execucao_id": sess["execucao_id"], "produto_id": pid}).status_code == 200
    assert _ext(hosp, token, "/api/assistida/captura", _corpo(sess["execucao_id"], pid)).status_code == 200
    assert c.post("/api/assistida/encerrar", {"execucao_id": sess["execucao_id"]}).status_code == 200

    # a coleta automática é recusada para todos, inclusive o admin
    for quem in (adm, c):
        r = quem.post("/api/coletar", {})
        assert r.status_code in (403, 404)
    assert adm.get("/api/assistida/token").status_code == 404  # token global não existe no modo hospedado
    assert tentativas == []


def test_navegador_e_coleta_automatica_recusam_no_modo_hospedado(hosp):
    from searching import run
    from searching.core.navegador import Navegador

    with pytest.raises(modo.OperacaoBloqueadaNoModoHospedado):
        Navegador()._criar()
    with pytest.raises(modo.OperacaoBloqueadaNoModoHospedado):
        hosp.server.rodar_coleta_cli("manual")
    with pytest.raises(modo.OperacaoBloqueadaNoModoHospedado):
        run.main([])


def test_so_o_navegador_do_coletor_importa_selenium():
    """Garantia estática: nenhum outro módulo do servidor sabe abrir uma loja (requests, urllib.request, selenium...)."""
    from pathlib import Path

    raiz = Path(__file__).parents[1] / "searching"
    proibidos = ("import requests", "from requests", "urllib.request", "import httpx", "http.client", "import aiohttp")
    achados = [f"{p.name}: {k}" for p in raiz.rglob("*.py") for k in proibidos if k in p.read_text(encoding="utf-8")]
    assert achados == []
    com_selenium = sorted(p.relative_to(raiz).as_posix() for p in raiz.rglob("*.py") if "selenium" in p.read_text(encoding="utf-8"))
    assert com_selenium  # existe (coletor automático, só modo local)
    assert all(not f.startswith(("assistida", "auth/", "web_conta")) for f in com_selenium)


def test_auditoria_registra_pareamento_e_revogacao(hosp):
    _, adm, cl = _preparar(hosp)
    c = cl["coletor@teste.com"]
    _parear(c)
    tid = c.get("/api/meus-tokens").get_json()[0]["id"]
    c.delete(f"/api/meus-tokens/{tid}")
    acoes = {a["acao"] for a in adm.get("/api/auditoria").get_json()}
    assert {"extensao_pareada", "token_revogado", "atribuicoes_alteradas"} <= acoes


def test_modo_local_continua_com_token_global(tmp_path, monkeypatch):
    import importlib
    import sys

    monkeypatch.setenv("SEARCHING_DB", str(tmp_path / "l.db"))
    monkeypatch.setenv("SEARCHING_PRINTS", str(tmp_path / "prints"))
    monkeypatch.delenv("SEARCHING_MODO", raising=False)
    sys.modules.pop("server", None)
    server = importlib.import_module("server")
    try:
        monkeypatch.setattr(server.assistida, "TOKEN_PATH", tmp_path / "assistida.token")
        c = server.app.test_client()
        token = c.get("/api/assistida/token").get_json()["token"]
        pid = c.post("/api/links", json={"nome": "Samsung Galaxy S25 256GB", "link": URL_S25}).get_json()["id"]
        sess = c.post("/api/assistida/iniciar", json={}).get_json()
        h = {"Origin": EXTENSAO, "X-Searching-Token": token}
        assert c.post("/api/assistida/autorizar", json={"execucao_id": sess["execucao_id"], "produto_id": pid}, headers=h).status_code == 200
        assert c.post("/api/assistida/captura", json=_corpo(sess["execucao_id"], pid), headers=h).status_code == 200
        assert c.post("/api/assistida/captura", json={}, headers={"Origin": EXTENSAO, "X-Searching-Token": "errado"}).status_code in (401, 403)
        assert c.post("/api/assistida/autorizar", json={}, headers={"Origin": EXTENSAO}).status_code == 403
    finally:
        sys.modules.pop("server", None)


def test_sessao_antiga_abandonada_nao_trava_produtos(hosp):
    pid, _, cl = _preparar(hosp, ("coletor@teste.com", "coletor2@teste.com"))
    a, b = cl["coletor@teste.com"], cl["coletor2@teste.com"]
    sa = a.post("/api/assistida/iniciar", {}).get_json()
    from searching.db.models import Execucao

    with hosp.fabrica() as s:
        s.get(Execucao, sa["execucao_id"]).iniciada_em = datetime.now() - timedelta(hours=13)
        s.commit()
    assert b.post("/api/assistida/iniciar", {}).status_code == 200
    assert pid
