from pathlib import Path

from searching.adapters import adaptador_para
from searching.adapters.magalu import MagaluAdapter
from searching.core.precos import PRECO_RE

FIXTURES = Path(__file__).parent / "fixtures"
URL_PRODUTO = "https://www.magazineluiza.com.br/celular-samsung-galaxy-s25/p/abc123/te/gs25/"


def _ler(nome: str, url: str = URL_PRODUTO):
    return MagaluAdapter.parse_pagina((FIXTURES / nome).read_text(encoding="utf-8"), url)


def test_pagina_de_produto():
    leitura = _ler("magalu_produto.html")
    assert leitura.titulo == "Celular Samsung Galaxy S25 5G, 256GB, 12GB RAM"
    assert leitura.pix_texto == "R$ 3.799,00"
    assert leitura.vendedor == "Samsung"
    assert not (leitura.bloqueio or leitura.pagina_404 or leitura.indisponivel)
    assert leitura.url_de_produto


def test_produto_indisponivel():
    leitura = _ler("magalu_indisponivel.html")
    assert leitura.titulo
    assert leitura.pix_texto is None
    assert leitura.indisponivel


def test_pagina_nao_encontrada():
    leitura = _ler("magalu_404.html", "https://www.magazineluiza.com.br/produto-antigo/p/zzz/")
    assert leitura.pagina_404


def test_bloqueio_por_captcha():
    leitura = _ler("magalu_captcha.html")
    assert leitura.bloqueio and leitura.titulo is None


def test_bloqueio_403_mesmo_com_h1():
    # Página real observada na coleta: a Magalu bloqueia o acesso automatizado com "Erro 403".
    leitura = _ler("magalu_403.html")
    assert leitura.titulo and leitura.bloqueio and leitura.pix_texto is None


def test_redirecionamento_para_busca_nao_e_produto():
    leitura = _ler("magalu_404.html", "https://www.magazineluiza.com.br/busca/galaxy+s25/")
    assert not leitura.url_de_produto


def test_codigo_e_urls_base():
    a = MagaluAdapter()
    url = "https://www.magazineluiza.com.br/celular-samsung-s25/p/abc123/te/gs25/?seller_id=samsung"
    assert a.codigo_produto(url) == "abc123"
    assert a.urls_base(url) == [
        "https://www.magazineluiza.com.br/celular-samsung-s25/p/abc123/",
        "https://www.magazineluiza.com.br/p/abc123/",
    ]
    # URL que já é só o caminho base não gera a mesma URL de novo
    assert a.urls_base("https://www.magazineluiza.com.br/p/abc123/") == []
    assert a.urls_base("https://www.magazineluiza.com.br/busca/s25/") == []
    assert a.codigo_produto("https://www.magazineluiza.com.br/") is None


def test_url_de_busca():
    a = MagaluAdapter()
    assert a.url_busca("Samsung Galaxy S25  256GB") == "https://www.magazineluiza.com.br/busca/Samsung%20Galaxy%20S25%20256GB/"
    assert a.url_busca("  ") is None


def test_parse_busca_deduplica_e_ignora_links_que_nao_sao_produto():
    html = (FIXTURES / "magalu_busca.html").read_text(encoding="utf-8")
    resultados = MagaluAdapter.parse_busca(html, "https://www.magazineluiza.com.br/busca/galaxy-s25/")
    assert [r.url for r in resultados] == [
        "https://www.magazineluiza.com.br/celular-samsung-galaxy-s25-ultra-5g-256gb/p/ultra001/te/g25u/",
        "https://www.magazineluiza.com.br/samsung-galaxy-s25-5g-256gb-azul/p/novo25/te/gs25/",
        "https://www.magazineluiza.com.br/celular-samsung-galaxy-a17-5g-128gb/p/a17x128/te/ga14/",
    ]
    assert resultados[1].titulo == "Samsung Galaxy S25 5G, 256GB, 12GB RAM"


def test_roteamento_por_dominio():
    assert isinstance(adaptador_para("https://www.magazinevoce.com.br/loja/x/p/abc/"), MagaluAdapter)
    assert adaptador_para("https://www.amazon.com.br/dp/B0") is None


# ---------- página REAL salva do Chrome (Ctrl+S, 2026-10-25) ----------
def test_pagina_real_da_magalu():
    """Cobre o layout de verdade: título no h1, PIX em price-value, vendedor em seller-delivery-text e cartão 1x escrito '01x'."""
    html = (FIXTURES / "magalu_real_produto.html").read_text(encoding="utf-8")
    leitura = MagaluAdapter().ler_html(html, "https://www.magazineluiza.com.br/celular-samsung-galaxy-s25/p/abc123/te/gs25/")
    assert leitura.titulo.startswith("Celular Samsung Galaxy S25 5G 256GB")
    assert leitura.vendedor == "Magalu"
    assert PRECO_RE.search(leitura.pix_texto).group(0).replace("\xa0", " ") == "R$ 3.899,00"
    assert leitura.cartao_texto.replace("\xa0", " ") == "R$ 4.332,22"  # 1x no cartão de crédito, não as parcelas com juros
    assert not (leitura.bloqueio or leitura.pagina_404 or leitura.indisponivel)


def test_cartao_1x_aceita_01x_mas_nao_11x():
    linha = lambda n: f'<table><tr data-testid="payment-table-Cartão de crédito-item"><td>{n} de R$ 100,00</td></tr></table>'  # noqa: E731
    assert MagaluAdapter.parse_cartao_1x(linha("01x")) == "R$ 100,00"
    assert MagaluAdapter.parse_cartao_1x(linha("1x")) == "R$ 100,00"
    assert MagaluAdapter.parse_cartao_1x(linha("11x")) is None
    assert MagaluAdapter.parse_cartao_1x(linha("21x")) is None
