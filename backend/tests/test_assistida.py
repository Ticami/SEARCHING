import base64
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from searching import assistida
from searching.alerts.email import ConfigSMTP
from searching.alerts.servico import Notificador
from searching.db import links
from searching.db.models import Alerta, Coleta, Configuracao, Execucao, RevisaoLink
from searching.db.session import criar_engine, iniciar_banco

FIXTURES = Path(__file__).parent / "fixtures"
PNG = "data:image/png;base64," + base64.b64encode(
    bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c6360000002000001e221bc330000000049454e44ae426082")
).decode()
URL_S25 = "https://www.magazineluiza.com.br/celular-samsung-galaxy-s25/p/abc123/te/gs25/"
SMTP = ConfigSMTP("smtp.teste", 587, "u@t", "s", "r@t", ("dest@t",))


def _html(nome):
    return (FIXTURES / nome).read_text(encoding="utf-8")


@pytest.fixture
def s(tmp_path):
    with iniciar_banco(criar_engine(tmp_path / "t.db"))() as sessao:
        yield sessao


@pytest.fixture
def produtos(s):
    return {
        "s25": links.criar(s, "Samsung Galaxy S25 256GB", URL_S25, "Magazine Luiza"),
        "a17": links.criar(s, "Samsung Galaxy A17 5G 128GB", "https://www.magazineluiza.com.br/a17/p/def456/", "Magazine Luiza"),
        "amazon": links.criar(s, "Samsung Galaxy S24 256GB", "https://www.amazon.com.br/dp/B0ABCDEFGH", "Amazon"),
    }


def _captura(**kw):
    base = {"url_final": URL_S25, "html": _html("magalu_produto.html"), "html_modal": _html("magalu_modal_pagamento.html"), "screenshot": PNG}
    base.update(kw)
    return base


def _caixa():
    enviadas = []
    return enviadas, Notificador(carregar_config=lambda: SMTP, enviar=lambda msg, cfg: enviadas.append(msg))


# ---------- token ----------
def test_token_e_estavel_e_so_o_certo_vale(tmp_path):
    caminho = tmp_path / "t.token"
    t = assistida.obter_token(caminho)
    assert len(t) >= 32 and assistida.obter_token(caminho) == t
    assert assistida.token_valido(t, caminho)
    assert not assistida.token_valido("outro", caminho) and not assistida.token_valido(None, caminho) and not assistida.token_valido("", caminho)


# ---------- sessão ----------
def test_iniciar_monta_a_fila_so_com_lojas_suportadas(s, produtos):
    sess = assistida.iniciar(s)
    assert sess["ativa"] and sess["total"] == 2 and sess["concluidos"] == 0
    assert [i["nome"] for i in sess["itens"]] == ["Samsung Galaxy S25 256GB", "Samsung Galaxy A17 5G 128GB"]  # a Amazon não tem adaptador
    assert sess["proximo_produto_id"] == produtos["s25"].id
    assert s.get(Execucao, sess["execucao_id"]).origem == "assistida"


def test_iniciar_sem_produtos_suportados_recusa(s):
    with pytest.raises(assistida.SessaoInvalida):
        assistida.iniciar(s)


def test_iniciar_de_novo_encerra_a_sessao_anterior(s, produtos):
    primeira = assistida.iniciar(s)["execucao_id"]
    segunda = assistida.iniciar(s)["execucao_id"]
    assert primeira != segunda and s.get(Execucao, primeira).finalizada_em is not None
    assert assistida.sessao(s)["execucao_id"] == segunda


def test_filtros_da_fila(s, produtos):
    sess = assistida.iniciar(s, include=["Samsung Galaxy A17 5G 128GB"])
    assert [i["nome"] for i in sess["itens"]] == ["Samsung Galaxy A17 5G 128GB"]


# ---------- captura ----------
def test_captura_ok_grava_precos_print_e_avanca_a_fila(s, produtos, tmp_path):
    sess = assistida.iniciar(s)
    r = assistida.registrar_captura(s, sess["execucao_id"], produtos["s25"].id, _captura(), prints_dir=tmp_path / "prints", notificador=_caixa()[1])
    assert (r["status"], r["pix_centavos"], r["cartao_1x_centavos"]) == ("OK", 379900, 399895)
    assert (r["pix"], r["cartao_1x"], r["vendedor"]) == ("R$ 3.799,00", "R$ 3.998,95", "Samsung")
    assert r["print_url"].startswith("/api/prints/")
    assert len(list((tmp_path / "prints").rglob("*.png"))) == 1

    depois = assistida.sessao(s)
    assert depois["concluidos"] == 1 and depois["proximo_produto_id"] == produtos["a17"].id
    assert depois["itens"][0]["coleta"]["status"] == "OK"


def test_captura_sem_menu_de_pagamento_deixa_o_cartao_vazio(s, produtos, tmp_path):
    sess = assistida.iniciar(s)
    r = assistida.registrar_captura(s, sess["execucao_id"], produtos["s25"].id, _captura(html_modal=None), prints_dir=tmp_path)
    assert r["status"] == "OK" and r["pix_centavos"] == 379900 and r["cartao_1x"] is None


@pytest.mark.parametrize("html, status", [
    ("magalu_403.html", "BLOQUEIO"),
    ("magalu_captcha.html", "BLOQUEIO"),
    ("magalu_404.html", "LINK_QUEBRADO"),
    ("magalu_indisponivel.html", "INDISPONIVEL"),
])
def test_paginas_de_erro_recebem_o_status_certo_e_o_print_fica_guardado(s, produtos, tmp_path, html, status):
    sess = assistida.iniciar(s)
    r = assistida.registrar_captura(s, sess["execucao_id"], produtos["s25"].id, _captura(html=_html(html), html_modal=None), prints_dir=tmp_path)
    assert r["status"] == status and r["pix_centavos"] is None and r["print_url"]


def test_produto_diferente_do_cadastro_e_divergente(s, produtos, tmp_path):
    sess = assistida.iniciar(s)
    ultra = _html("magalu_produto.html").replace("Galaxy S25 5G", "Galaxy S25 Ultra 5G")
    r = assistida.registrar_captura(s, sess["execucao_id"], produtos["s25"].id, _captura(html=ultra), prints_dir=tmp_path)
    assert r["status"] == "PRODUTO_DIVERGENTE"


def test_preco_muito_diferente_vira_suspeito_e_nao_alerta(s, produtos, tmp_path):
    sess = assistida.iniciar(s)
    s.add(Coleta(produto_id=produtos["s25"].id, coletado_em=datetime.now() - timedelta(days=1), status="OK", preco_pix_centavos=379900))
    s.commit()
    barato = _html("magalu_produto.html").replace("R$ 3.799,00", "R$ 100,00")
    enviadas, notificador = _caixa()
    r = assistida.registrar_captura(s, sess["execucao_id"], produtos["s25"].id, _captura(html=barato), prints_dir=tmp_path, notificador=notificador)
    assert r["status"] == "SUSPEITO" and r["alerta"] is None and enviadas == []


def test_queda_de_preco_envia_o_email_com_o_print_anexado(s, produtos, tmp_path):
    sess = assistida.iniciar(s)
    s.add(Coleta(produto_id=produtos["s25"].id, coletado_em=datetime.now() - timedelta(days=1), status="OK", preco_pix_centavos=420000))
    s.commit()
    enviadas, notificador = _caixa()
    r = assistida.registrar_captura(s, sess["execucao_id"], produtos["s25"].id, _captura(), prints_dir=tmp_path, notificador=notificador)
    assert r["status"] == "OK" and r["variacao_pct"] == -9.55 and r["preco_anterior"] == "R$ 4.200,00"
    assert r["alerta"] == {"enviado": True, "erro": None} and len(enviadas) == 1
    assert [a.get_content_type() for a in enviadas[0].iter_attachments()] == ["image/png"]
    assert s.scalars(select(Alerta)).one().sucesso


def test_refazer_gera_nova_coleta_e_vale_a_ultima(s, produtos, tmp_path):
    sess = assistida.iniciar(s)
    assistida.registrar_captura(s, sess["execucao_id"], produtos["s25"].id, _captura(html=_html("magalu_403.html")), prints_dir=tmp_path)
    assistida.registrar_captura(s, sess["execucao_id"], produtos["s25"].id, _captura(), prints_dir=tmp_path)
    item = assistida.sessao(s)["itens"][0]
    assert item["coleta"]["status"] == "OK" and s.query(Coleta).count() == 2


@pytest.mark.parametrize("ruim, trecho", [
    ({"html": ""}, "HTML"),
    ({"screenshot": "data:image/png;base64,bm90IGEgcG5n"}, "PNG"),
    ({"screenshot": "data:image/png;base64,@@@@"}, "base64|PNG"),
])
def test_capturas_invalidas_sao_recusadas_sem_gravar_nada(s, produtos, tmp_path, ruim, trecho):
    sess = assistida.iniciar(s)
    with pytest.raises(assistida.SessaoInvalida, match=trecho):
        assistida.registrar_captura(s, sess["execucao_id"], produtos["s25"].id, _captura(**ruim), prints_dir=tmp_path)
    assert s.query(Coleta).count() == 0


def test_so_aceita_captura_da_sessao_aberta_e_de_produto_da_fila(s, produtos, tmp_path):
    sess = assistida.iniciar(s)
    with pytest.raises(assistida.SessaoInvalida):
        assistida.registrar_captura(s, sess["execucao_id"] + 99, produtos["s25"].id, _captura(), prints_dir=tmp_path)
    with pytest.raises(assistida.SessaoInvalida):
        assistida.registrar_captura(s, sess["execucao_id"], produtos["amazon"].id, _captura(), prints_dir=tmp_path)  # fora da fila


# ---------- pular, link quebrado, encerrar ----------
def test_pular_e_link_quebrado(s, produtos, tmp_path):
    sess = assistida.iniciar(s)
    ex = sess["execucao_id"]
    depois = assistida.pular(s, ex, produtos["s25"].id)
    assert depois["itens"][0]["pulado"] and depois["proximo_produto_id"] == produtos["a17"].id

    c = assistida.registrar_link_quebrado(s, ex, produtos["a17"].id)
    assert c["status"] == "LINK_QUEBRADO" and "usuário" in c["detalhe"]
    revisao = s.scalars(select(RevisaoLink)).one()
    assert (revisao.produto_id, revisao.estado, revisao.candidatos) == (produtos["a17"].id, "pendente", [])
    assistida.registrar_link_quebrado(s, ex, produtos["a17"].id)  # de novo: não duplica a revisão
    assert s.query(RevisaoLink).count() == 1
    assert assistida.sessao(s)["concluidos"] == 2 and assistida.sessao(s)["proximo_produto_id"] is None


def test_encerrar_fecha_a_execucao_com_os_totais(s, produtos, tmp_path):
    sess = assistida.iniciar(s)
    ex = sess["execucao_id"]
    assistida.registrar_captura(s, ex, produtos["s25"].id, _captura(html=_html("magalu_403.html")), prints_dir=tmp_path)  # 1ª tentativa bloqueada
    assistida.registrar_captura(s, ex, produtos["s25"].id, _captura(), prints_dir=tmp_path)  # refeita: OK
    assistida.registrar_link_quebrado(s, ex, produtos["a17"].id)

    resumo = assistida.encerrar(s, ex)
    assert (resumo["total"], resumo["coletados"], resumo["ok"], resumo["falhas"], resumo["em_revisao"]) == (2, 2, 1, 1, 1)
    assert resumo["por_status"] == {"OK": 1, "LINK_QUEBRADO": 1}  # a falha refeita não conta
    execucao = s.get(Execucao, ex)
    assert execucao.finalizada_em is not None and (execucao.ok, execucao.falhas) == (1, 1)
    assert assistida.sessao(s) == {"ativa": False}
    assistida.encerrar(s, ex)  # idempotente


def test_resumo_por_email_so_se_ligado(s, produtos, tmp_path):
    ex = assistida.iniciar(s)["execucao_id"]
    assistida.registrar_captura(s, ex, produtos["s25"].id, _captura(), prints_dir=tmp_path)
    enviadas, notificador = _caixa()
    assistida.encerrar(s, ex, notificador=notificador)
    assert enviadas == []

    ex2 = assistida.iniciar(s)["execucao_id"]
    s.merge(Configuracao(chave="resumo_diario_email", valor="1"))
    s.commit()
    assistida.registrar_captura(s, ex2, produtos["s25"].id, _captura(), prints_dir=tmp_path)
    assistida.encerrar(s, ex2, notificador=notificador)
    assert len(enviadas) == 1 and enviadas[0]["Subject"].startswith("[SEARCHING] Resumo: 1/1")


# ---------- adaptador ----------
def test_cartao_1x_nao_confunde_com_11x_e_12x():
    from searching.adapters.magalu import MagaluAdapter

    assert MagaluAdapter.parse_cartao_1x(_html("magalu_modal_pagamento.html")) == "R$ 3.998,95"
    so_parcelado = '<tr data-testid="payment-table-Cartão de crédito-item-10"><td>11x</td><td>R$ 363,54</td></tr>'
    assert MagaluAdapter.parse_cartao_1x(so_parcelado) is None
    assert MagaluAdapter.parse_cartao_1x("") is None



def test_duas_paginas_bloqueadas_seguidas_param_de_abrir_paginas(s, produtos):
    from searching.core.status import StatusColeta

    ex = assistida.iniciar(s, stores=["magalu"], agora=datetime.now())["execucao_id"]
    agora = datetime.now()
    for i, chave in enumerate(("s25", "a17")):
        s.add(Coleta(execucao_id=ex, produto_id=produtos[chave].id, coletado_em=agora - timedelta(minutes=1, seconds=i),
                     status=StatusColeta.BLOQUEIO.value))
    s.commit()
    with pytest.raises(assistida.LimiteExcedido, match="bloqueou 2 páginas seguidas"):
        assistida.autorizar_abertura(s, ex, produtos["s25"].id, agora=agora)
    # passada a pausa, a loja volta a ser tentada
    assert assistida.autorizar_abertura(s, ex, produtos["s25"].id, agora=agora + timedelta(minutes=11))["ok"]
