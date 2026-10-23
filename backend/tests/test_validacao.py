import pytest

from searching.core.status import StatusColeta
from searching.core.validacao import Leitura, classificar, eh_suspeito, titulo_confere

S25 = dict(marca="Samsung", modelo="Galaxy S25", armazenamento="256GB", extras="")
S25_ULTRA = dict(marca="Samsung", modelo="Galaxy S25", armazenamento="256GB", extras="ULTRA")
A17_128 = dict(marca="Samsung", modelo="Galaxy A17", armazenamento="128GB", extras="5G")
S24_PLUS = dict(marca="Samsung", modelo="Galaxy S24", armazenamento="256GB", extras="+")
FLIP_FE = dict(marca="Samsung", modelo="Galaxy Z Flip7", armazenamento="128GB", extras="FE")


@pytest.mark.parametrize(
    "titulo, cadastro, esperado",
    [
        ("Celular Samsung Galaxy S25 5G, 256GB, 12GB RAM, Câmera Tripla de 50+12+10, Tela Grande de 6.2\"", S25, True),
        ("Samsung Galaxy S25 5G 256GB Galaxy AI Azul Marinho 6.2 12GB RAM Cam Tripla 50+12+10MP", S25, True),
        # S25 não pode virar S25 Ultra, nem o contrário
        ("Celular Samsung Galaxy S25 Ultra 5G, 256GB, 12GB RAM", S25, False),
        ("Celular Samsung Galaxy S25, 256GB, 12GB RAM", S25_ULTRA, False),
        ("Celular Samsung Galaxy S25 FE 5G, 256GB, 8GB RAM", S25, False),
        ("Celular Samsung Galaxy S25 Edge 5G, 256GB", S25, False),
        # A17 128 GB não pode virar o de 256 GB
        ("Celular Samsung Galaxy A17 5G com IA, 128GB, 4GB RAM, Câm de 50MP", A17_128, True),
        ("Celular Samsung Galaxy A17 5G com IA, 256GB, 8GB RAM, Câm de 50MP", A17_128, False),
        # S24+ x S24
        ("Celular Samsung Galaxy S24+, 256GB, 12GB de RAM, Tela de 6.7\"", S24_PLUS, True),
        ("Celular Samsung Galaxy S24, 256GB, 8GB de RAM", S24_PLUS, False),
        ("Celular Samsung Galaxy S24+, 256GB, 12GB de RAM", dict(S24_PLUS, extras=""), False),
        # S2 não casa com S25
        ("Celular Samsung Galaxy S25, 256GB", dict(S25, modelo="Galaxy S2"), False),
        ("Celular Samsung Galaxy Z Flip7 FE, 128GB, 8GB RAM", FLIP_FE, True),
        ("Celular Samsung Galaxy Z Flip7, 128GB, 8GB RAM", FLIP_FE, False),
        ("Celular Motorola Moto G, 128GB", S25, False),
        ("", S25, False),
        (None, S25, False),
    ],
)
def test_titulo_confere(titulo, cadastro, esperado):
    ok, motivo = titulo_confere(titulo, **cadastro)
    assert ok is esperado, motivo


def test_eh_suspeito():
    assert eh_suspeito(100000, 200000, 40)  # queda de 50%
    assert eh_suspeito(300000, 200000, 40)  # alta de 50%
    assert not eh_suspeito(190000, 200000, 40)
    assert not eh_suspeito(100000, None, 40)
    assert not eh_suspeito(None, 200000, 40)


def _leitura(**kw):
    base = dict(url_final="https://x/p/abc/", titulo="Celular Samsung Galaxy S25 5G, 256GB", pix_texto="R$ 3.799,00")
    base.update(kw)
    return Leitura(**base)


@pytest.mark.parametrize(
    "leitura, pix, esperado",
    [
        (_leitura(), 379900, StatusColeta.OK),
        (_leitura(), None, StatusColeta.PRECO_NAO_ENCONTRADO),  # nunca OK sem preço
        (_leitura(bloqueio=True, titulo=None), None, StatusColeta.BLOQUEIO),
        (_leitura(pagina_404=True, titulo=None), None, StatusColeta.LINK_QUEBRADO),
        (_leitura(url_de_produto=False, url_final="https://x/busca/s25/"), 379900, StatusColeta.LINK_QUEBRADO),
        (_leitura(titulo=None), None, StatusColeta.LINK_QUEBRADO),
        (_leitura(titulo=None, carregou=False), None, StatusColeta.TIMEOUT),
        (_leitura(titulo="Celular Samsung Galaxy S25 Ultra, 256GB"), 379900, StatusColeta.PRODUTO_DIVERGENTE),
        (_leitura(indisponivel=True), None, StatusColeta.INDISPONIVEL),
    ],
)
def test_classificar(leitura, pix, esperado):
    status, _ = classificar(leitura, pix, **S25)
    assert status == esperado
