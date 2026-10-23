from pathlib import Path

from searching.adapters import adaptador_para
from searching.adapters.magalu import MagaluAdapter

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


def test_roteamento_por_dominio():
    assert isinstance(adaptador_para("https://www.magazinevoce.com.br/loja/x/p/abc/"), MagaluAdapter)
    assert adaptador_para("https://www.amazon.com.br/dp/B0") is None
