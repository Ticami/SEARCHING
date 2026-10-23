import pytest

from searching.core.atributos import extrair_atributos


@pytest.mark.parametrize(
    "nome, marca, modelo, armazenamento, extras",
    [
        ("Samsung Galaxy S25 256GB", "Samsung", "Galaxy S25", "256GB", ()),
        ("Samsung Galaxy S25 Ultra 256GB", "Samsung", "Galaxy S25", "256GB", ("ULTRA",)),
        ("Samsung Galaxy S25 FE 5G 128GB", "Samsung", "Galaxy S25", "128GB", ("5G", "FE")),
        ("Samsung Galaxy S24+ 256GB", "Samsung", "Galaxy S24", "256GB", ("+",)),
        ("Samsung Galaxy Z Fold 7 1TB", "Samsung", "Galaxy Z Fold 7", "1TB", ()),
        ("Samsung Galaxy A17 5G 128GB", "Samsung", "Galaxy A17", "128GB", ("5G",)),
    ],
)
def test_extrair_atributos(nome, marca, modelo, armazenamento, extras):
    a = extrair_atributos(nome)
    assert (a.marca, a.modelo, a.armazenamento, a.extras) == (marca, modelo, armazenamento, extras)


def test_variantes_nao_se_confundem():
    s25 = extrair_atributos("Samsung Galaxy S25 256GB")
    ultra = extrair_atributos("Samsung Galaxy S25 Ultra 256GB")
    a17_128 = extrair_atributos("Samsung Galaxy A17 5G 128GB")
    a17_256 = extrair_atributos("Samsung Galaxy A17 5G 256GB")
    assert s25.extras != ultra.extras
    assert a17_128.armazenamento != a17_256.armazenamento
