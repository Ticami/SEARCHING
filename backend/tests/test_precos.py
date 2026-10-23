import pytest

from searching.core.precos import formatar_brl, parse_preco_centavos


@pytest.mark.parametrize(
    "texto, esperado",
    [
        ("R$ 3.167 , 12", 316712),  # formato legado com espaços
        ("R$ 1.299,00", 129900),
        ("R$ 999,90", 99990),
        ("R$ 10.999,99 à vista", 1099999),
        ("1299,00", 129900),
        ("", None),
        (None, None),
        ("N/A", None),
        ("Indisponível", None),
    ],
)
def test_parse_preco_centavos(texto, esperado):
    assert parse_preco_centavos(texto) == esperado


def test_formatar_brl():
    assert formatar_brl(316712) == "R$ 3.167,12"
    assert formatar_brl(99) == "R$ 0,99"
    assert formatar_brl(None) == "N/A"
