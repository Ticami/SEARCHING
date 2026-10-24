"""Modo hospedado: login, papéis, deny by default, CSRF, bloqueio, recuperação de senha, 2FA e auditoria."""
import importlib
import re
import sys
from datetime import datetime, timedelta

import pytest
from conftest import SENHA, URL_S25
from sqlalchemy import select

from searching.auth import politicas as pol
from searching.auth import servico, totp
from searching.db.models import Auditoria, Usuario

LEITURA = ("GET", "HEAD", "OPTIONS")


def _url(rule):
    return re.sub(r"<(?:\w+:)?\w+>", "1", rule.rule)


def _regras(app):
    for rule in app.url_map.iter_rules():
        for metodo in sorted(rule.methods - {"HEAD", "OPTIONS"}):
            yield rule, metodo


# ---------- toda rota tem política ----------
def test_toda_rota_tem_politica_no_modo_hospedado(hosp):
    sem = [r.endpoint for r in hosp.server.app.url_map.iter_rules() if r.endpoint not in pol.POLITICAS]
    assert sem == [], f"rotas sem política em politicas.py: {sem}"


def test_toda_rota_tem_politica_no_modo_local(tmp_path, monkeypatch):
    monkeypatch.setenv("SEARCHING_DB", str(tmp_path / "l.db"))
    monkeypatch.delenv("SEARCHING_MODO", raising=False)
    sys.modules.pop("server", None)
    server = importlib.import_module("server")
    try:
        sem = [r.endpoint for r in server.app.url_map.iter_rules() if r.endpoint not in pol.POLITICAS]
        assert sem == []
    finally:
        sys.modules.pop("server", None)


def test_politicas_nao_apontam_para_rotas_que_nao_existem(hosp):
    existentes = {r.endpoint for r in hosp.server.app.url_map.iter_rules()}
    fantasmas = set(pol.POLITICAS) - existentes
    assert fantasmas == set()


def test_rota_sem_politica_responde_403(hosp):
    app = hosp.server.app

    @app.route("/api/rota-esquecida")
    def rota_esquecida():
        return "x"

    r = hosp.cliente("admin@teste.com").get("/api/rota-esquecida")
    assert r.status_code == 403


# ---------- sem login ----------
def test_sem_login_toda_rota_nao_publica_recusa(hosp):
    c = hosp.cliente()
    for rule, metodo in _regras(hosp.server.app):
        if pol.POLITICAS[rule.endpoint].acesso == pol.PUBLICA:
            continue
        r = c.req(metodo.lower(), _url(rule), json={} if metodo != "GET" else None)
        assert r.status_code in (401, 404), (metodo, rule.rule, r.status_code)  # 404 = rota que não existe neste modo
        assert r.status_code != 404 or pol.POLITICAS[rule.endpoint].so_local, (metodo, rule.rule)


# ---------- leitor: nenhuma escrita, nenhuma coleta ----------
def test_leitor_nao_consegue_nenhuma_escrita_nem_disparar_coleta(hosp):
    c = hosp.cliente("leitor@teste.com")
    testadas = 0
    for rule, metodo in _regras(hosp.server.app):
        p = pol.POLITICAS[rule.endpoint]
        if metodo in LEITURA or p.acesso in (pol.PUBLICA, pol.LOGADO) or p.escrita_leitura:
            continue
        r = c.req(metodo.lower(), _url(rule), json={})
        esperado = (401,) if p.acesso == pol.EXTENSAO else (403, 404)
        assert r.status_code in esperado, (metodo, rule.rule, r.status_code)
        testadas += 1
    assert testadas >= 15


def test_leitor_nao_dispara_coleta_nem_acessa_internet(hosp, monkeypatch):
    chamadas = []
    monkeypatch.setattr(hosp.server.subprocess, "run", lambda *a, **k: chamadas.append(a))
    c = hosp.cliente("leitor@teste.com")
    for url in ("/api/coletar", "/api/assistida/iniciar", "/api/assistida/captura", "/api/assistida/autorizar",
                "/api/assistida/pular", "/api/assistida/encerrar", "/api/assistida/link-quebrado"):
        assert c.post(url, {}).status_code in (401, 403, 404), url
    assert chamadas == []


def test_leitor_pode_ver_o_que_e_de_leitura(hosp):
    c = hosp.cliente("leitor@teste.com")
    for url in ("/api/links", "/api/historico", "/api/saude", "/api/alertas", "/api/alertas/regras", "/api/revisoes",
                "/api/prints-galeria", "/api/links/historico", "/api/assistida/em-coleta"):
        assert c.get(url).status_code == 200, url
    assert c.post("/api/historico/exportar", {"ids": []}).status_code in (200, 400)  # leitura (Excel): não é bloqueada
    assert c.get("/api/usuarios").status_code == 403
    assert c.get("/api/auditoria").status_code == 403


# ---------- coletor ----------
def _novo_produto(hosp, nome="Samsung Galaxy S25 256GB", link=URL_S25):
    adm = hosp.cliente("admin@teste.com")
    r = adm.post("/api/links", {"nome": nome, "link": link})
    assert r.status_code == 200, r.get_json()
    return adm, r.get_json()["id"]


def test_coletor_so_edita_o_que_lhe_foi_atribuido(hosp):
    adm, pid = _novo_produto(hosp)
    col = hosp.cliente("coletor@teste.com")
    novo = URL_S25.replace("abc123", "zzz999")
    corpo = {"id": pid, "nome": "Samsung Galaxy S25 256GB", "link": novo}
    assert col.put("/api/links", corpo).status_code == 403
    assert col.put(f"/api/alertas/regras/{pid}", {"alerta_pct": 7}).status_code == 403
    assert adm.put(f"/api/atribuicoes/{hosp.uid('coletor@teste.com')}", {"produtos": [pid]}).status_code == 200
    assert col.put("/api/links", corpo).status_code == 200
    assert col.put(f"/api/alertas/regras/{pid}", {"alerta_pct": 7}).status_code == 200
    # mesmo atribuído, o coletor não cria, apaga nem mexe em configurações
    assert col.post("/api/links", {"nome": "Outro", "link": URL_S25}).status_code == 403
    assert col.delete("/api/links", {"id": pid}).status_code == 403
    assert col.put("/api/alertas/config", {}).status_code == 403
    assert col.get("/api/usuarios").status_code == 403


def test_coletor_nao_resolve_revisao_de_produto_alheio(hosp):
    from searching.db.models import RevisaoLink

    adm, pid = _novo_produto(hosp)
    with hosp.fabrica() as s:
        r = RevisaoLink(produto_id=pid, motivo="LINK_QUEBRADO", candidatos=[])
        s.add(r)
        s.commit()
        rid = r.id
    col = hosp.cliente("coletor@teste.com")
    assert col.post(f"/api/revisoes/{rid}/resolver", {"acao": "desativar"}).status_code == 403
    adm.put(f"/api/atribuicoes/{hosp.uid('coletor@teste.com')}", {"produtos": [pid]})
    assert col.post(f"/api/revisoes/{rid}/resolver", {"acao": "desativar"}).status_code == 200


def test_coletor_nao_acessa_rotas_de_admin(hosp):
    c = hosp.cliente("coletor@teste.com")
    for rule, metodo in _regras(hosp.server.app):
        p = pol.POLITICAS[rule.endpoint]
        if p.acesso != pol.ADMIN:
            continue
        assert c.req(metodo.lower(), _url(rule), json={}).status_code in (403, 404), (metodo, rule.rule)


# ---------- login ----------
def test_login_com_cookie_httponly_samesite_e_mensagem_generica(hosp):
    c = hosp.cliente()
    r = c.login("admin@teste.com")
    assert r.status_code == 200 and r.get_json()["usuario"]["papel"] == "admin"
    cookie = r.headers["Set-Cookie"]
    assert "HttpOnly" in cookie and "SameSite=Lax" in cookie and "Secure" in cookie
    assert "argon2" not in r.get_data(as_text=True) and "senha_hash" not in r.get_data(as_text=True)
    errada = hosp.cliente().login("admin@teste.com", "outra-senha-errada")
    inexistente = hosp.cliente().login("ninguem@teste.com", "outra-senha-errada")
    assert errada.status_code == inexistente.status_code == 401
    assert errada.get_json()["error"] == inexistente.get_json()["error"]


def test_bloqueio_temporario_depois_de_cinco_falhas(hosp):
    c = hosp.cliente()
    for _ in range(servico.FALHAS_PARA_BLOQUEAR):
        assert c.login("coletor@teste.com", "errada-errada-12").status_code == 401
    r = c.login("coletor@teste.com")  # mesmo com a senha certa, a conta está bloqueada
    assert r.status_code == 423
    with hosp.fabrica() as s:
        u = s.scalar(select(Usuario).where(Usuario.email == "coletor@teste.com"))
        u.bloqueado_ate = datetime.now() - timedelta(seconds=1)
        s.commit()
    assert hosp.cliente().login("coletor@teste.com").status_code == 200


def test_limite_de_falhas_por_ip(hosp):
    c = hosp.cliente()
    for i in range(servico.LIMITE_FALHAS_IP):
        c.login(f"alvo{i}@teste.com", "errada-errada-12")
    assert c.login("admin@teste.com").status_code == 429


def test_escrita_exige_csrf_e_origem(hosp):
    c = hosp.cliente("admin@teste.com")
    corpo = {"nome": "Samsung Galaxy S25 256GB", "link": URL_S25}
    sem_csrf = c.req("post", "/api/links", json=corpo, headers={"X-CSRF-Token": "falso"})
    assert sem_csrf.status_code == 403
    assert c.req("post", "/api/links", json=corpo, origem="https://evil.com").status_code == 403
    assert c.req("post", "/api/links", json=corpo, origem=None).status_code == 403  # sem Origin: recusa no hospedado
    assert c.post("/api/links", corpo).status_code == 200


def test_host_de_fora_e_recusado(hosp):
    r = hosp.server.app.test_client().get("/api/links", base_url="https://evil.com")
    assert r.status_code == 403


def test_logout_encerra_a_sessao(hosp):
    c = hosp.cliente("admin@teste.com")
    assert c.get("/api/links").status_code == 200
    antigo = c.c.get_cookie("searching_sessao", domain="searching.teste")
    assert c.post("/api/auth/logout").status_code == 200
    c2 = hosp.cliente()
    c2.c.set_cookie("searching_sessao", antigo.value, domain="searching.teste")
    assert c2.get("/api/links").status_code == 401


def test_sessao_expira_por_inatividade(hosp):
    c = hosp.cliente("admin@teste.com")
    from searching.db.models import SessaoLogin

    with hosp.fabrica() as s:
        for x in s.scalars(select(SessaoLogin)):
            x.ultimo_uso = datetime.now() - timedelta(hours=servico.SESSAO_OCIOSA_H + 1)
        s.commit()
    assert c.get("/api/links").status_code == 401


def test_desativar_usuario_derruba_a_sessao_na_hora(hosp):
    adm = hosp.cliente("admin@teste.com")
    col = hosp.cliente("coletor@teste.com")
    assert col.get("/api/links").status_code == 200
    assert adm.patch(f"/api/usuarios/{hosp.uid('coletor@teste.com')}", {"ativo": False}).status_code == 200
    assert col.get("/api/links").status_code == 401
    assert hosp.cliente().login("coletor@teste.com").status_code == 401


# ---------- gestão de usuários ----------
def test_admin_cria_usuario_com_senha_provisoria_e_troca_obrigatoria(hosp):
    adm = hosp.cliente("admin@teste.com")
    r = adm.post("/api/usuarios", {"email": "Novo@Teste.com", "nome": "Novo", "papel": "coletor"})
    assert r.status_code == 201
    temporaria = r.get_json()["senha_temporaria"]
    novo = hosp.cliente()
    assert novo.login("novo@teste.com", temporaria).status_code == 200
    assert novo.get("/api/links").status_code == 403  # precisa trocar a senha antes
    assert novo.get("/api/auth/eu").status_code == 200
    assert novo.post("/api/auth/trocar-senha", {"atual": temporaria, "nova": "curta"}).status_code == 400
    assert novo.post("/api/auth/trocar-senha", {"atual": temporaria, "nova": "Outra-Senha-Forte-9"}).status_code == 200
    assert novo.get("/api/links").status_code == 200


def test_nao_deixa_o_sistema_sem_administrador(hosp):
    adm = hosp.cliente("admin@teste.com")
    uid = hosp.uid("admin@teste.com")
    assert adm.patch(f"/api/usuarios/{uid}", {"papel": "leitor"}).status_code == 409
    assert adm.patch(f"/api/usuarios/{uid}", {"ativo": False}).status_code == 409
    r = adm.post("/api/usuarios", {"email": "adm2@teste.com", "papel": "admin"})
    assert r.status_code == 201


def test_politica_de_senha(hosp):
    adm = hosp.cliente("admin@teste.com")
    c = hosp.cliente("coletor@teste.com")
    assert c.post("/api/auth/trocar-senha", {"atual": SENHA, "nova": "curta"}).status_code == 400
    assert c.post("/api/auth/trocar-senha", {"atual": "errada", "nova": "Outra-Senha-Forte-9"}).status_code == 403
    assert adm.post("/api/usuarios", {"email": "mal", "papel": "leitor"}).status_code == 400
    assert adm.post("/api/usuarios", {"email": "a@b.com", "papel": "dono"}).status_code == 400


def test_trocar_senha_encerra_as_outras_sessoes(hosp):
    a, b = hosp.cliente("coletor@teste.com"), hosp.cliente("coletor@teste.com")
    assert a.post("/api/auth/trocar-senha", {"atual": SENHA, "nova": "Outra-Senha-Forte-9"}).status_code == 200
    assert a.get("/api/links").status_code == 200
    assert b.get("/api/links").status_code == 401


# ---------- recuperação de senha ----------
def _token_do_email(msg):
    return re.search(r"token=([\w-]+)", msg.get_body(("plain",)).get_content()).group(1)


def test_recuperacao_de_senha_por_email_uso_unico(hosp):
    c = hosp.cliente()
    generica = c.post("/api/auth/recuperar", {"email": "leitor@teste.com"})
    inexistente = c.post("/api/auth/recuperar", {"email": "fantasma@teste.com"})
    assert generica.status_code == inexistente.status_code == 200 and generica.get_json() == inexistente.get_json()
    assert len(hosp.emails) == 1 and hosp.emails[0]["To"] == "leitor@teste.com"
    token = _token_do_email(hosp.emails[0])
    assert c.post("/api/auth/redefinir", {"token": token, "senha": "curta"}).status_code == 400
    assert c.post("/api/auth/redefinir", {"token": token, "senha": "Nova-Senha-Forte-7"}).status_code == 200
    assert c.post("/api/auth/redefinir", {"token": token, "senha": "Nova-Senha-Forte-8"}).status_code == 400  # uso único
    assert c.login("leitor@teste.com").status_code == 401
    assert c.login("leitor@teste.com", "Nova-Senha-Forte-7").status_code == 200


def test_link_de_redefinicao_expira(hosp):
    c = hosp.cliente()
    c.post("/api/auth/recuperar", {"email": "leitor@teste.com"})
    token = _token_do_email(hosp.emails[0])
    from searching.db.models import RedefinicaoSenha

    with hosp.fabrica() as s:
        for r in s.scalars(select(RedefinicaoSenha)):
            r.expira_em = datetime.now() - timedelta(minutes=1)
        s.commit()
    assert c.post("/api/auth/redefinir", {"token": token, "senha": "Nova-Senha-Forte-7"}).status_code == 400


# ---------- 2FA ----------
def test_dois_fatores_opcional(hosp):
    c = hosp.cliente("coletor@teste.com")
    dados = c.post("/api/auth/2fa/iniciar").get_json()
    assert dados["uri"].startswith("otpauth://totp/")
    assert c.post("/api/auth/2fa/ativar", {"codigo": "000000"}).status_code == 400
    assert c.post("/api/auth/2fa/ativar", {"codigo": totp.codigo_atual(dados["segredo"])}).status_code == 200

    outro = hosp.cliente()
    r = outro.login("coletor@teste.com")
    assert r.status_code == 401 and r.get_json()["codigo"] == "2fa_necessario"
    assert outro.login("coletor@teste.com", codigo="000000").status_code == 401
    assert outro.login("coletor@teste.com", codigo=totp.codigo_atual(dados["segredo"])).status_code == 200
    assert c.post("/api/auth/2fa/desativar", {"senha": SENHA}).status_code == 200
    assert hosp.cliente().login("coletor@teste.com").status_code == 200


def test_totp_confere_com_vetor_da_rfc_6238():
    segredo = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"  # "12345678901234567890" em base32
    assert totp.codigo_atual(segredo, agora=59) == "287082"
    assert totp.verificar(segredo, "287082", agora=59) and not totp.verificar(segredo, "287083", agora=59)


# ---------- auditoria ----------
def test_auditoria_registra_quem_fez_o_que(hosp):
    adm = hosp.cliente("admin@teste.com")
    hosp.cliente().login("admin@teste.com", "errada-errada-12")
    adm.post("/api/links", {"nome": "Samsung Galaxy S25 256GB", "link": URL_S25})
    hosp.cliente("leitor@teste.com").post("/api/links", {"nome": "x", "link": URL_S25})
    log = adm.get("/api/auditoria").get_json()
    acoes = {(a["usuario"], a["acao"]) for a in log}
    assert ("admin@teste.com", "login_ok") in acoes
    assert ("admin@teste.com", "escrita") in acoes
    assert ("admin@teste.com", "login_falha") in acoes
    assert ("leitor@teste.com", "acesso_negado") in acoes
    assert adm.get("/api/auditoria?acao=login_ok").get_json()[0]["acao"] == "login_ok"


# ---------- modo local intacto ----------
def test_modo_local_nao_tem_login(tmp_path, monkeypatch):
    monkeypatch.setenv("SEARCHING_DB", str(tmp_path / "l.db"))
    monkeypatch.delenv("SEARCHING_MODO", raising=False)
    sys.modules.pop("server", None)
    server = importlib.import_module("server")
    try:
        c = server.app.test_client()
        assert c.get("/api/links").status_code == 200
        eu = c.get("/api/auth/eu").get_json()
        assert eu["modo"] == "local" and eu["usuario"]["papel"] == "admin"
        assert c.get("/api/modo").get_json() == {"modo": "local", "login": False}
        assert c.post("/api/auth/login", json={"email": "a@b.com", "senha": "x"}).status_code == 404
        assert c.get("/api/usuarios").status_code == 404 or c.get("/api/usuarios").status_code == 200
    finally:
        sys.modules.pop("server", None)


# ---------- CLI ----------
def test_cli_cria_admin_sem_senha_padrao(hosp):
    from searching import usuarios

    saidas, senhas = [], iter(["Admin-Cli-Forte-1", "Admin-Cli-Forte-1"])
    cod = usuarios.main(["criar-admin", "--email", "dono@teste.com"], fabrica=hosp.fabrica, ler_senha=lambda _: next(senhas), saida=saidas.append)
    assert cod == 0 and "criado como admin" in saidas[0]
    assert hosp.cliente().login("dono@teste.com", "Admin-Cli-Forte-1").status_code == 200
    # senhas diferentes ou fracas não criam nada
    senhas = iter(["Admin-Cli-Forte-1", "outra"])
    assert usuarios.main(["criar-admin", "--email", "x@teste.com"], fabrica=hosp.fabrica, ler_senha=lambda _: next(senhas), saida=saidas.append) == 1
    senhas = iter(["curta", "curta"])
    assert usuarios.main(["criar-admin", "--email", "y@teste.com"], fabrica=hosp.fabrica, ler_senha=lambda _: next(senhas), saida=saidas.append) == 1
    with hosp.fabrica() as s:
        assert s.scalar(select(Usuario.id).where(Usuario.email == "x@teste.com")) is None
        assert s.scalar(select(Auditoria.id).where(Auditoria.acao == "usuario_criado_cli"))


def test_modo_hospedado_exige_url_https(monkeypatch):
    from searching import modo

    with pytest.raises(modo.ModoInvalido):
        modo.url_publica({"SEARCHING_URL_PUBLICA": "http://searching.exemplo.com"})
    with pytest.raises(modo.ModoInvalido):
        modo.url_publica({})
    assert modo.url_publica({"SEARCHING_URL_PUBLICA": "https://searching.exemplo.com/"}) == "https://searching.exemplo.com"
    with pytest.raises(modo.ModoInvalido):
        modo.modo({"SEARCHING_MODO": "nuvem"})


def test_health_aceita_host_interno_e_o_resto_nao(hosp):
    c = hosp.server.app.test_client()
    assert c.get("/api/health", base_url="http://127.0.0.1:8000").status_code == 200
    assert c.get("/api/links", base_url="http://127.0.0.1:8000").status_code == 403
