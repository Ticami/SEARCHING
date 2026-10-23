from datetime import datetime, timedelta

import pytest

from searching.alerts.regras import Regra, UltimoAlerta, avaliar, preco_referencia

AGORA = datetime(2026, 10, 23, 12, 0)
REGRA = Regra(pct_queda=5, base_comparacao="ultimo", janela_dias=30, degrau_pct=2)


def d(dias_atras, preco):
    return (AGORA - timedelta(days=dias_atras), preco)


def test_referencia_por_base():
    hist = [d(40, 50000), d(10, 120000), d(5, 100000), d(1, 110000)]
    assert preco_referencia("ultimo", hist, AGORA, 30) == 110000
    assert preco_referencia("minimo_n_dias", hist, AGORA, 30) == 100000  # o de 40 dias fica fora da janela
    assert preco_referencia("media_n_dias", hist, AGORA, 30) == 110000
    assert preco_referencia("ultimo", [], AGORA, 30) is None
    assert preco_referencia("minimo_n_dias", [d(40, 50000)], AGORA, 30) is None  # nada na janela
    with pytest.raises(ValueError):
        preco_referencia("outra", hist, AGORA, 30)


def test_queda_abaixo_do_limite_nao_alerta():
    assert avaliar(REGRA, 96000, AGORA, [d(1, 100000)], None) is None  # 4%


def test_queda_no_limite_alerta_com_percentual():
    r = avaliar(REGRA, 95000, AGORA, [d(1, 100000)], None)
    assert r and r.queda_pct == 5.0 and r.preco_anterior_centavos == 100000 and r.motivos == ("queda",)


def test_aumento_de_preco_nao_alerta():
    assert avaliar(REGRA, 120000, AGORA, [d(1, 100000)], None) is None


def test_sem_historico_nao_alerta_por_queda():
    assert avaliar(REGRA, 50000, AGORA, [], None) is None


def test_preco_alvo_alerta_mesmo_sem_queda_e_sem_historico():
    regra = Regra(5, "ultimo", 30, 2, preco_alvo_centavos=100000)
    r = avaliar(regra, 99000, AGORA, [], None)
    assert r and r.motivos == ("preco_alvo",) and r.queda_pct == 0
    assert avaliar(regra, 101000, AGORA, [d(1, 101000)], None) is None


def test_queda_e_preco_alvo_juntos():
    regra = Regra(5, "ultimo", 30, 2, preco_alvo_centavos=95000)
    assert avaliar(regra, 90000, AGORA, [d(1, 100000)], None).motivos == ("queda", "preco_alvo")


def test_mesmo_preco_nao_reenvia():
    ultimo = UltimoAlerta(90000, AGORA - timedelta(days=1))
    regra = Regra(5, "ultimo", 30, 2, preco_alvo_centavos=95000)
    # preço-alvo continua atingido, mas o preço é o mesmo do último alerta
    assert avaliar(regra, 90000, AGORA, [d(1, 90000)], ultimo) is None


def test_novo_alerta_so_se_cair_mais_um_degrau():
    ultimo = UltimoAlerta(90000, AGORA - timedelta(days=1))
    regra = Regra(5, "minimo_n_dias", 30, 2)
    hist = [d(3, 100000), d(1, 90000)]
    assert avaliar(regra, 89000, AGORA, hist, ultimo) is None  # só 1,1% abaixo do alerta e <5% do mínimo
    assert avaliar(Regra(1, "minimo_n_dias", 30, 2), 89000, AGORA, hist, ultimo) is None  # queda ok (1,1%), mas sem degrau de 2%
    r = avaliar(Regra(1, "minimo_n_dias", 30, 2), 88000, AGORA, hist, ultimo)  # 2,2% abaixo do último alerta
    assert r and r.preco_atual_centavos == 88000


def test_subiu_e_voltou_a_cair_alerta_de_novo():
    ultimo = UltimoAlerta(90000, AGORA - timedelta(days=3))
    hist = [d(5, 100000), d(3, 90000), d(2, 97000), d(1, 97000)]  # subiu depois do alerta
    r = avaliar(REGRA, 90000, AGORA, hist, ultimo)  # caiu de novo para o mesmo preço
    assert r and r.preco_anterior_centavos == 97000


def test_sem_subida_o_mesmo_preco_nao_alerta_de_novo():
    ultimo = UltimoAlerta(90000, AGORA - timedelta(days=3))
    hist = [d(5, 100000), d(3, 90000), d(1, 90000)]
    assert avaliar(Regra(5, "minimo_n_dias", 30, 2), 90000, AGORA, hist, ultimo) is None
