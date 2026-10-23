from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from searching.alerts import config as cfg_alertas
from searching.alerts.email import (
    ConfigEmailIncompleta,
    ConfigSMTP,
    carregar_config_smtp,
    construir_alerta,
    construir_resumo,
    status_config,
)
from searching.alerts.regras import Decisao
from searching.alerts.servico import Notificador, enviar_teste, processar_coleta, reenviar_pendentes
from searching.db.models import Alerta, Coleta, Produto
from searching.db.session import CONFIG_PADRAO, criar_engine, iniciar_banco

SMTP = ConfigSMTP("smtp.teste", 587, "u@teste", "segredo", "remetente@teste", ("a@teste", "b@teste"))
ENV_OK = {"SMTP_HOST": "smtp.gmail.com", "SMTP_USER": "eu@gmail.com", "SMTP_PASSWORD": "abcd efgh ijkl mnop", "ALERTA_DESTINATARIOS": "eu@gmail.com, outro@x.com"}


# ---------- configuração SMTP / .env ----------
def test_config_smtp_completa_e_normalizada():
    c = carregar_config_smtp(ENV_OK)
    assert (c.host, c.port, c.usuario, c.remetente) == ("smtp.gmail.com", 587, "eu@gmail.com", "eu@gmail.com")
    assert c.senha == "abcdefghijklmnop"  # espaços da senha de app removidos
    assert c.destinatarios == ("eu@gmail.com", "outro@x.com")


def test_config_smtp_incompleta_diz_o_que_falta():
    with pytest.raises(ConfigEmailIncompleta) as erro:
        carregar_config_smtp({"SMTP_HOST": "smtp.gmail.com"})
    assert "SMTP_USER" in str(erro.value) and "SMTP_PASSWORD" in str(erro.value) and "ALERTA_DESTINATARIOS" in str(erro.value)
    with pytest.raises(ConfigEmailIncompleta):
        carregar_config_smtp({**ENV_OK, "SMTP_PORT": "abc"})


def test_status_da_configuracao_nunca_expoe_a_senha():
    st = status_config(ENV_OK)
    assert st["configurado"] and "abcd" not in str(st) and st["destinatarios"] == ["eu@gmail.com", "outro@x.com"]
    assert status_config({})["configurado"] is False


# ---------- mensagem ----------
def _coleta(tmp_path, preco=90000, com_print=True, **kw):
    caminho = None
    if com_print:
        arq = tmp_path / "print.png"
        arq.write_bytes(b"\x89PNG-falso")
        caminho = str(arq)  # caminho absoluto é aceito
    return Coleta(id=1, produto_id=1, coletado_em=datetime(2026, 10, 23, 12, 5), status="OK", preco_pix_centavos=preco, caminho_print=caminho, **kw)


def _produto(**kw):
    base = dict(id=1, nome_comercial="Samsung Galaxy S25 256GB", loja="Magazine Luiza", url_atual="https://exemplo.com/s25/p/1/",
                marca="Samsung", modelo="Galaxy S25", armazenamento="256GB", extras="")
    base.update(kw)
    return Produto(**base)


def test_email_de_alerta_tem_dados_e_print_anexado(tmp_path):
    decisao = Decisao(100000, 90000, 10.0, ("queda",))
    msg = construir_alerta(_produto(), _coleta(tmp_path), decisao, "pix", "remetente@teste", ("a@teste", "b@teste"))
    assert msg["To"] == "a@teste, b@teste" and msg["From"] == "remetente@teste"
    assert "R$ 900,00" in msg["Subject"] and "-10,0%" in msg["Subject"]
    corpo = msg.get_body(("html",)).get_content()
    for esperado in ("Samsung Galaxy S25 256GB", "Magazine Luiza", "R$ 1.000,00", "R$ 900,00", "-10,0%", "23/10/2026 12:05", "https://exemplo.com/s25/p/1/"):
        assert esperado in corpo
    anexos = list(msg.iter_attachments())
    assert len(anexos) == 1 and anexos[0].get_content_type() == "image/png" and anexos[0].get_filename() == "print.png"


def test_email_sem_print_avisa_e_nao_quebra(tmp_path):
    msg = construir_alerta(_produto(), _coleta(tmp_path, com_print=False), Decisao(100000, 90000, 10.0, ("preco_alvo",)), "pix", "r@t", ("a@t",))
    assert list(msg.iter_attachments()) == []
    assert "Print indisponível" in msg.get_body(("plain",)).get_content() and "preço-alvo atingido" in msg.get_body(("plain",)).get_content()


def test_nome_do_produto_e_escapado_no_html(tmp_path):
    msg = construir_alerta(_produto(nome_comercial="<script>x</script>"), _coleta(tmp_path), Decisao(100000, 90000, 10.0, ("queda",)), "pix", "r@t", ("a@t",))
    corpo = msg.get_body(("html",)).get_content()
    assert "<script>" not in corpo and "&lt;script&gt;" in corpo


def test_resumo_diario():
    msg = construir_resumo(
        {"total": 12, "ok": 9, "falhas": 3, "links_corrigidos": 1, "em_revisao": 1, "alertas": 2, "por_status": {"OK": 9, "BLOQUEIO": 3}},
        datetime(2026, 10, 23, 12, 30), "r@t", ("a@t",),
    )
    texto = msg.get_body(("plain",)).get_content()
    assert "12" in texto and "BLOQUEIO (3)" in texto and "Quedas de preço detectadas: 2" in texto
    assert "9/12" in msg["Subject"]


# ---------- serviço (banco + regras + envio) ----------
class Caixa:
    """Notificador falso que guarda as mensagens e pode simular falha de envio."""

    def __init__(self, falhar=False):
        self.enviadas, self.falhar = [], falhar

    def notificador(self):
        def enviar(msg, cfg):
            if self.falhar:
                raise ConnectionRefusedError("sem conexão")
            self.enviadas.append(msg)

        return Notificador(carregar_config=lambda: SMTP, enviar=enviar)


@pytest.fixture
def s(tmp_path):
    with iniciar_banco(criar_engine(tmp_path / "t.db"))() as sessao:
        yield sessao


@pytest.fixture
def produto(s):
    p = Produto(nome_comercial="Samsung Galaxy S25 256GB", loja="Magazine Luiza", url_atual="https://x/p/1/", marca="Samsung", modelo="Galaxy S25", armazenamento="256GB")
    s.add(p)
    s.commit()
    return p


T0 = datetime.now().replace(microsecond=0) - timedelta(days=10)


def _coletar(s, produto, dias, preco, status="OK", cartao=None):
    c = Coleta(produto_id=produto.id, coletado_em=T0 + timedelta(days=dias), status=status, preco_pix_centavos=preco, preco_cartao_1x_centavos=cartao)
    s.add(c)
    s.commit()
    return c


def test_sequencia_de_precos_alerta_so_quando_deve(s, produto):
    caixa, cfg = Caixa(), dict(CONFIG_PADRAO)
    n = caixa.notificador()
    resultados = []
    for dia, preco in [(0, 100000), (1, 90000), (2, 90000), (3, 97000), (4, 90000)]:
        c = _coletar(s, produto, dia, preco)
        resultados.append(bool(processar_coleta(s, produto, c, cfg, n)))
    # 1ª sem histórico; 2ª cai 10% (alerta); 3ª mesmo preço (nada); 4ª subiu (nada); 5ª caiu de novo (alerta)
    assert resultados == [False, True, False, False, True]
    assert len(caixa.enviadas) == 2
    alertas = s.scalars(select(Alerta).order_by(Alerta.id)).all()
    assert [(a.preco_anterior_centavos, a.preco_atual_centavos, a.queda_pct, a.sucesso) for a in alertas] == [
        (100000, 90000, 10.0, True), (97000, 90000, 7.22, True)]
    assert alertas[0].destinatario == "a@teste, b@teste" and alertas[0].base_preco == "pix"


@pytest.mark.parametrize("status", ["SUSPEITO", "PRECO_NAO_ENCONTRADO", "BLOQUEIO", "LINK_QUEBRADO"])
def test_coleta_que_nao_e_ok_nunca_alerta(s, produto, status):
    caixa = Caixa()
    _coletar(s, produto, 0, 100000)
    c = _coletar(s, produto, 1, 50000, status=status)
    assert processar_coleta(s, produto, c, dict(CONFIG_PADRAO), caixa.notificador()) is None
    assert caixa.enviadas == []


def test_preco_suspeito_do_passado_nao_serve_de_referencia(s, produto):
    caixa = Caixa()
    _coletar(s, produto, 0, 100000)
    _coletar(s, produto, 1, 20000, status="SUSPEITO")  # leitura errada: não conta como "último preço válido"
    c = _coletar(s, produto, 2, 97000)
    assert processar_coleta(s, produto, c, dict(CONFIG_PADRAO), caixa.notificador()) is None  # 3% de queda sobre 100.000


def test_regra_do_produto_sobrepoe_a_global(s, produto):
    caixa = Caixa()
    produto.alerta_pct = 2.0
    _coletar(s, produto, 0, 100000)
    c = _coletar(s, produto, 1, 97000)  # 3%: abaixo dos 5% globais, acima dos 2% do produto
    assert processar_coleta(s, produto, c, dict(CONFIG_PADRAO), caixa.notificador())
    assert len(caixa.enviadas) == 1


def test_preco_alvo_do_produto(s, produto):
    caixa = Caixa()
    produto.alerta_preco_alvo_centavos = 95000
    _coletar(s, produto, 0, 96000)
    c = _coletar(s, produto, 1, 94000)  # só 2% de queda, mas passou do alvo
    a = processar_coleta(s, produto, c, dict(CONFIG_PADRAO), caixa.notificador())
    assert a and a.motivos == "preco_alvo"


def test_base_cartao_1x(s, produto):
    caixa = Caixa()
    _coletar(s, produto, 0, 100000, cartao=110000)
    c = _coletar(s, produto, 1, 100000, cartao=100000)  # PIX igual, cartão caiu 9%
    cfg = {**CONFIG_PADRAO, "alerta_base_preco": "cartao_1x"}
    a = processar_coleta(s, produto, c, cfg, caixa.notificador())
    assert a and a.base_preco == "cartao_1x" and a.preco_atual_centavos == 100000
    assert processar_coleta(s, produto, _coletar(s, produto, 2, 100000, cartao=None), cfg, caixa.notificador()) is None  # sem preço na base


def test_alertas_desligados(s, produto):
    _coletar(s, produto, 0, 100000)
    c = _coletar(s, produto, 1, 50000)
    assert processar_coleta(s, produto, c, {**CONFIG_PADRAO, "alertas_ativos": "0"}, Caixa().notificador()) is None


def test_falha_de_envio_fica_registrada_e_e_reenviada_depois(s, produto):
    quebrada = Caixa(falhar=True)
    _coletar(s, produto, 0, 100000)
    c = _coletar(s, produto, 1, 90000)
    a = processar_coleta(s, produto, c, dict(CONFIG_PADRAO), quebrada.notificador())  # não lança
    assert a.sucesso is False and "ConnectionRefusedError" in a.erro

    ok = Caixa()
    assert reenviar_pendentes(s, ok.notificador()) == 1
    s.refresh(a)
    assert a.sucesso is True and a.erro is None and len(ok.enviadas) == 1
    assert reenviar_pendentes(s, ok.notificador()) == 0  # nada mais pendente


def test_email_nao_configurado_registra_o_motivo(s, produto):
    def sem_config():
        raise ConfigEmailIncompleta("E-mail não configurado: faltam SMTP_USER no arquivo .env")

    _coletar(s, produto, 0, 100000)
    c = _coletar(s, produto, 1, 90000)
    a = processar_coleta(s, produto, c, dict(CONFIG_PADRAO), Notificador(carregar_config=sem_config, enviar=lambda m, c: None))
    assert a.sucesso is False and "SMTP_USER" in a.erro


def test_email_de_teste():
    caixa = Caixa()
    ok, msg = enviar_teste(caixa.notificador())
    assert ok and "a@teste" in msg and caixa.enviadas[0]["Subject"] == "[SEARCHING] E-mail de teste"
    ok, msg = enviar_teste(Caixa(falhar=True).notificador())
    assert not ok and "ConnectionRefusedError" in msg


# ---------- configuração global ----------
def test_validacao_da_configuracao(s):
    assert cfg_alertas.validar("alerta_pct_queda", "7,5") == "7.5"
    assert cfg_alertas.validar("alerta_base_comparacao", "media_n_dias") == "media_n_dias"
    assert cfg_alertas.validar("alertas_ativos", "sim") == "1"
    for chave, ruim in [("alerta_pct_queda", "0"), ("alerta_pct_queda", "150"), ("alerta_pct_queda", "abc"), ("alerta_dias_janela", "0"),
                        ("alerta_base_preco", "boleto"), ("alerta_base_comparacao", "x"), ("alertas_ativos", "talvez")]:
        with pytest.raises(ValueError):
            cfg_alertas.validar(chave, ruim)


def test_salvar_config_e_tudo_ou_nada(s):
    novos = cfg_alertas.salvar_config(s, {"alerta_pct_queda": "8", "alerta_base_preco": "cartao_1x"})
    assert novos["alerta_pct_queda"] == "8" and novos["alerta_base_preco"] == "cartao_1x"
    with pytest.raises(ValueError):
        cfg_alertas.salvar_config(s, {"alerta_pct_queda": "9", "alerta_dias_janela": "0"})
    assert cfg_alertas.ler_config(s)["alerta_pct_queda"] == "8"  # a válida não foi gravada junto com a inválida
    with pytest.raises(ValueError):
        cfg_alertas.salvar_config(s, {"retentativas": "9"})  # só chaves de alerta
