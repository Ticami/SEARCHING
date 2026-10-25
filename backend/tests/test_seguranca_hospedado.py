"""Segurança extra do modo hospedado: limite de requisições, sessões ativas, 2FA de admin, ids da extensão e retenção de prints."""
from datetime import datetime, timedelta

from conftest import EXTENSAO, SENHA, URL_S25
from sqlalchemy import select

from searching import retencao, seguranca
from searching.auth import limite, totp
from searching.db.models import Coleta, Produto
from test_hospedado_extensao import _corpo, _parear, _preparar


# ---------- limite de requisições ----------
def test_limitador_de_janela_deslizante():
    t = [0.0]
    lim = limite.Limitador(relogio=lambda: t[0])
    assert all(lim.permitir(("a",), 3) is None for _ in range(3))
    espera = lim.permitir(("a",), 3)
    assert espera is not None and 0 < espera <= 60
    assert lim.permitir(("b",), 3) is None  # outra chave tem a própria cota
    t[0] = 61
    assert lim.permitir(("a",), 3) is None
    assert lim.permitir(("a",), 0) is None  # 0 desliga


def test_rotas_da_api_tem_limite_por_usuario(hosp, monkeypatch):
    monkeypatch.setenv("SEARCHING_LIMITE_REQ_MIN", "5")
    c = hosp.cliente("leitor@teste.com")
    codigos = [c.get("/api/links").status_code for _ in range(7)]
    assert codigos[:5] == [200] * 5 and codigos[5:] == [429, 429]
    r = c.get("/api/links")
    assert r.status_code == 429 and int(r.headers["Retry-After"]) >= 1
    # outra pessoa não é afetada
    assert hosp.cliente("coletor@teste.com").get("/api/links").status_code == 200


def test_limite_de_escritas_e_de_exportacao(hosp, monkeypatch):
    monkeypatch.setenv("SEARCHING_LIMITE_ESCRITA_MIN", "3")
    monkeypatch.setenv("SEARCHING_LIMITE_EXPORTAR_MIN", "2")
    adm = hosp.cliente("admin@teste.com")
    escritas = [adm.put("/api/alertas/config", {}).status_code for _ in range(5)]
    assert escritas[3:] == [429, 429] and 429 not in escritas[:3]
    leitor = hosp.cliente("leitor@teste.com")
    exports = [leitor.post("/api/historico/exportar", {"ids": []}).status_code for _ in range(3)]
    assert exports[2] == 429 and 429 not in exports[:2]


def test_requisicoes_sem_login_tambem_tem_limite_por_ip(hosp, monkeypatch):
    monkeypatch.setenv("SEARCHING_LIMITE_REQ_MIN", "4")
    c = hosp.cliente()
    codigos = [c.get("/api/links").status_code for _ in range(6)]
    assert codigos[:4] == [401] * 4 and codigos[4:] == [429, 429]
    assert c.get("/api/health").status_code == 200  # health check nunca é limitado


# ---------- sessões ativas ----------
def test_listar_e_encerrar_as_proprias_sessoes(hosp):
    a, b = hosp.cliente("coletor@teste.com"), hosp.cliente("coletor@teste.com")
    lista = a.get("/api/minhas-sessoes").get_json()
    assert len(lista) == 2 and [x["atual"] for x in lista].count(True) == 1
    outra = next(x for x in lista if not x["atual"])
    assert a.delete(f"/api/minhas-sessoes/{outra['id']}").status_code == 200
    assert b.get("/api/links").status_code == 401  # a sessão encerrada cai na hora
    assert a.get("/api/links").status_code == 200
    # não encerra sessão de outra pessoa
    alheia = hosp.cliente("leitor@teste.com").get("/api/minhas-sessoes").get_json()[0]
    assert a.delete(f"/api/minhas-sessoes/{alheia['id']}").status_code == 404


def test_encerrar_todas_as_outras_sessoes(hosp):
    a, b, c = (hosp.cliente("coletor@teste.com") for _ in range(3))
    assert a.post("/api/minhas-sessoes/encerrar-outras").status_code == 200
    assert b.get("/api/links").status_code == 401 and c.get("/api/links").status_code == 401
    assert a.get("/api/links").status_code == 200


def test_admin_ve_e_encerra_sessoes_de_qualquer_um(hosp):
    adm, col = hosp.cliente("admin@teste.com"), hosp.cliente("coletor@teste.com")
    todas = adm.get("/api/sessoes").get_json()
    alvo = next(x for x in todas if x["usuario"] == "coletor@teste.com")
    assert adm.delete(f"/api/sessoes/{alvo['id']}").status_code == 200
    assert col.get("/api/links").status_code == 401
    assert col.get("/api/sessoes").status_code in (401, 403)
    assert hosp.cliente("leitor@teste.com").get("/api/sessoes").status_code == 403


# ---------- 2FA obrigatório para admin ----------
def test_admin_sem_2fa_so_acessa_a_configuracao_do_2fa(hosp, monkeypatch):
    monkeypatch.setenv("SEARCHING_2FA_ADMIN", "1")
    adm = hosp.cliente("admin@teste.com")
    eu = adm.get("/api/auth/eu").get_json()
    assert eu["precisa_2fa"] is True
    r = adm.get("/api/links")
    assert r.status_code == 403 and r.get_json()["codigo"] == "2fa_obrigatorio"
    assert adm.get("/api/usuarios").status_code == 403
    dados = adm.post("/api/auth/2fa/iniciar").get_json()
    assert adm.post("/api/auth/2fa/ativar", {"codigo": totp.codigo_atual(dados["segredo"])}).status_code == 200
    assert adm.get("/api/links").status_code == 200
    assert adm.get("/api/auth/eu").get_json()["precisa_2fa"] is False
    # depois de ativado, o admin não consegue desligar
    assert adm.post("/api/auth/2fa/desativar", {"senha": SENHA}).status_code == 409


def test_2fa_de_admin_nao_vale_para_coletor_nem_leitor_e_pode_ser_desligado(hosp, monkeypatch):
    monkeypatch.setenv("SEARCHING_2FA_ADMIN", "1")
    assert hosp.cliente("coletor@teste.com").get("/api/links").status_code == 200
    assert hosp.cliente("leitor@teste.com").get("/api/links").status_code == 200
    monkeypatch.setenv("SEARCHING_2FA_ADMIN", "0")
    assert hosp.cliente("admin@teste.com").get("/api/links").status_code == 200


def test_promover_a_admin_passa_a_exigir_2fa(hosp, monkeypatch):
    monkeypatch.setenv("SEARCHING_2FA_ADMIN", "1")
    # admin de teste precisa ativar o 2FA para administrar
    adm = hosp.cliente("admin@teste.com")
    d = adm.post("/api/auth/2fa/iniciar").get_json()
    adm.post("/api/auth/2fa/ativar", {"codigo": totp.codigo_atual(d["segredo"])})
    col = hosp.cliente("coletor@teste.com")
    assert col.get("/api/links").status_code == 200
    adm.patch(f"/api/usuarios/{hosp.uid('coletor@teste.com')}", {"papel": "admin"})
    r = col.get("/api/links")
    assert r.status_code == 403 and r.get_json()["codigo"] == "2fa_obrigatorio"


# ---------- ids da extensão ----------
def test_extensao_so_com_id_da_lista(hosp, monkeypatch):
    pid, _, cl = _preparar(hosp)
    c = cl["coletor@teste.com"]
    token = _parear(c)
    sess = c.post("/api/assistida/iniciar", {}).get_json()
    corpo = {"execucao_id": sess["execucao_id"], "produto_id": pid}

    def chamar(origem, rota="/api/assistida/autorizar", dados=corpo):
        cli = hosp.server.app.test_client()
        h = {"X-Searching-Token": token}
        if origem:
            h["Origin"] = origem
        return cli.post(rota, json=dados, headers=h, base_url="https://searching.teste")

    assert chamar(EXTENSAO).status_code == 200  # sem lista: basta o token

    monkeypatch.setenv("SEARCHING_EXTENSAO_IDS", "idoficialdaextensao,outroidedge")
    for origem in (EXTENSAO, "chrome-extension://idoficialdaextensaoXX", "https://evil.com", None):
        r = chamar(origem)
        assert r.status_code == 403, origem
    assert chamar(EXTENSAO, "/api/assistida/captura", _corpo(sess["execucao_id"], pid)).status_code == 403
    with hosp.fabrica() as s:
        assert s.scalar(select(Coleta.id)) is None
    for ok in ("chrome-extension://idoficialdaextensao", "chrome-extension://outroidedge"):
        assert chamar(ok).status_code in (200, 429)  # 429 = intervalo de 3 s, mas passou pela lista


def test_funcao_da_lista_de_ids():
    env = {"SEARCHING_EXTENSAO_IDS": " abc , def "}
    assert seguranca.ids_extensao_permitidos(env) == {"abc", "def"}
    assert seguranca.extensao_autorizada("chrome-extension://abc", env)
    assert not seguranca.extensao_autorizada("chrome-extension://ab", env)
    assert not seguranca.extensao_autorizada("moz-extension://abc", env)
    assert seguranca.extensao_autorizada(None, {})  # sem lista, vale só o token


# ---------- retenção de prints ----------
def _coleta_com_print(s, produto, prints, dias_atras, nome):
    pasta = prints / f"dia-{nome}"
    pasta.mkdir(parents=True, exist_ok=True)
    arquivo = pasta / f"{nome}.png"
    arquivo.write_bytes(b"\x89PNG\r\n\x1a\nx")
    c = Coleta(produto_id=produto.id, coletado_em=datetime.now() - timedelta(days=dias_atras), status="OK",
               preco_pix_centavos=100, caminho_print=str(arquivo))
    s.add(c)
    s.commit()
    return arquivo


def _produto(s):
    p = Produto(nome_comercial="X", loja="Magalu", url_atual=URL_S25)
    s.add(p)
    s.flush()
    return p


def test_retencao_apaga_prints_antigos_e_mantem_o_historico(hosp, tmp_path):
    prints = tmp_path / "prints"
    with hosp.fabrica() as s:
        p = _produto(s)
        velho = _coleta_com_print(s, p, prints, 40, "velho")
        novo = _coleta_com_print(s, p, prints, 2, "novo")
        simulada = retencao.aplicar(s, 30, simular=True, prints_dir=prints)
        assert simulada["removidos"] == 1 and velho.exists()  # simulação não mexe em nada
        r = retencao.aplicar(s, 30, prints_dir=prints)
        assert r["removidos"] == 1 and not velho.exists() and novo.exists()
        assert not velho.parent.exists()  # pasta de data vazia some
        coletas = s.scalars(select(Coleta).order_by(Coleta.id)).all()
        assert coletas[0].caminho_print is None and coletas[0].preco_pix_centavos == 100  # preço continua no histórico
        assert coletas[1].caminho_print
        assert retencao.aplicar(s, 0, prints_dir=prints)["removidos"] == 0  # 0 = guardar para sempre


def test_retencao_arquiva_em_vez_de_apagar(hosp, tmp_path):
    prints, arquivo = tmp_path / "prints", tmp_path / "arquivo"
    with hosp.fabrica() as s:
        p = _produto(s)
        velho = _coleta_com_print(s, p, prints, 90, "velho")
        r = retencao.aplicar(s, 30, prints_dir=prints, arquivo_dir=arquivo)
        assert r["arquivados"] == 1 and not velho.exists()
        assert (arquivo / "dia-velho" / "velho.png").exists()


def test_retencao_nunca_mexe_em_arquivo_fora_da_pasta_de_prints(hosp, tmp_path):
    prints = tmp_path / "prints"
    prints.mkdir()
    fora = tmp_path / "importante.txt"
    fora.write_text("não apague")
    with hosp.fabrica() as s:
        p = _produto(s)
        s.add(Coleta(produto_id=p.id, coletado_em=datetime.now() - timedelta(days=400), status="OK", caminho_print=str(fora)))
        s.commit()
        assert retencao.aplicar(s, 30, prints_dir=prints)["removidos"] == 0
    assert fora.exists()


def test_admin_configura_e_aplica_a_retencao(hosp):
    adm = hosp.cliente("admin@teste.com")
    assert adm.get("/api/retencao").get_json() == {"dias": 0}
    assert adm.put("/api/retencao", {"dias": 45}).get_json() == {"dias": 45}
    assert adm.put("/api/retencao", {"dias": -3}).status_code == 400
    assert adm.put("/api/retencao", {"dias": "abc"}).status_code == 400
    r = adm.post("/api/retencao/aplicar", {"simular": True})
    assert r.status_code == 200 and r.get_json()["dias"] == 45 and r.get_json()["simulacao"] is True
    for quem in ("coletor@teste.com", "leitor@teste.com"):
        c = hosp.cliente(quem)
        assert c.get("/api/retencao").status_code == 403 and c.put("/api/retencao", {"dias": 1}).status_code == 403
        assert c.post("/api/retencao/aplicar", {}).status_code == 403


def test_variavel_de_ambiente_manda_na_retencao(hosp, monkeypatch):
    monkeypatch.setenv("SEARCHING_RETENCAO_PRINTS_DIAS", "7")
    with hosp.fabrica() as s:
        assert retencao.dias_configurados(s) == 7


def test_cli_reter_prints(hosp, tmp_path, monkeypatch):
    from searching import operacao

    monkeypatch.setenv("SEARCHING_DB", str(tmp_path / "h.db"))
    saidas = []
    assert operacao.main(["reter-prints", "--dias", "30", "--simular"], saida=saidas.append) == 0
    assert "simulação" in saidas[0]
