import pytest
from sqlalchemy import select

from searching.db import links
from searching.db.models import HistoricoLink, RevisaoLink
from searching.db.session import criar_engine, iniciar_banco


@pytest.fixture
def s(tmp_path):
    with iniciar_banco(criar_engine(tmp_path / "t.db"))() as sessao:
        yield sessao


def test_criar_calcula_atributos_e_infere_loja(s):
    p = links.criar(s, "Samsung Galaxy S25 FE 5G 128GB", "https://www.magazineluiza.com.br/x/p/abc/")
    assert p.loja == "Magazine Luiza"
    assert (p.marca, p.modelo, p.armazenamento, p.extras) == ("Samsung", "Galaxy S25", "128GB", "5G,FE")
    with pytest.raises(links.LinkInvalido):
        links.criar(s, "Samsung Galaxy S25 FE 5G 128GB", "https://www.magazineluiza.com.br/y/p/def/")
    with pytest.raises(links.LinkInvalido):
        links.criar(s, "", "https://x")


def test_trocar_url_fica_no_historico_e_reverte(s):
    p = links.criar(s, "Samsung Galaxy S25 256GB", "https://m.com/a/p/1/")
    links.trocar_url(s, p, "https://m.com/b/p/2/", "teste", "automatico", 0.95)
    s.commit()
    h = s.scalars(select(HistoricoLink)).one()
    assert (h.url_antiga, h.url_nova, h.origem, h.nota_confianca) == ("https://m.com/a/p/1/", "https://m.com/b/p/2/", "automatico", 0.95)

    links.reverter(s, h)
    s.commit()
    assert p.url_atual == "https://m.com/a/p/1/"
    assert s.query(HistoricoLink).count() == 2  # a reversão também fica registrada
    with pytest.raises(links.LinkInvalido):
        links.reverter(s, h)  # o link atual já não é o que essa troca definiu


def test_atualizar_nome_recalcula_atributos_e_barra_duplicata(s):
    a = links.criar(s, "Samsung Galaxy S25 256GB", "https://m.com/a/p/1/", "Magazine Luiza")
    links.criar(s, "Samsung Galaxy S25 Ultra 256GB", "https://m.com/b/p/2/", "Magazine Luiza")
    links.atualizar(s, a, "Samsung Galaxy S25 512GB", None, None)
    assert a.armazenamento == "512GB"
    with pytest.raises(links.LinkInvalido):
        links.atualizar(s, a, "Samsung Galaxy S25 Ultra 256GB", None, None)


def test_recriar_produto_desativado_reativa_e_mantem_historico(s):
    p = links.criar(s, "Samsung Galaxy S25 256GB", "https://m.com/a/p/1/", "Magazine Luiza")
    links.desativar(s, p)
    novo = links.criar(s, "Samsung Galaxy S25 256GB", "https://m.com/z/p/9/", "Magazine Luiza")
    assert novo.id == p.id and novo.ativo and novo.url_atual == "https://m.com/z/p/9/"


def test_resolver_revisao(s):
    p = links.criar(s, "Samsung Galaxy S25 256GB", "https://m.com/a/p/1/", "Magazine Luiza")
    r1 = RevisaoLink(produto_id=p.id, motivo="LINK_QUEBRADO", candidatos=[])
    r2 = RevisaoLink(produto_id=p.id, motivo="LINK_QUEBRADO", candidatos=[])
    s.add_all([r1, r2])
    s.flush()

    with pytest.raises(links.LinkInvalido):
        links.resolver_revisao(s, r1, "aprovar", "")
    links.resolver_revisao(s, r1, "aprovar", "https://m.com/n/p/5/")
    assert p.url_atual == "https://m.com/n/p/5/" and r1.estado == "aprovado" and r1.resolvido_em
    with pytest.raises(links.LinkInvalido):
        links.resolver_revisao(s, r1, "desativar")  # já resolvida

    links.resolver_revisao(s, r2, "desativar")
    assert p.ativo is False and r2.estado == "rejeitado"
