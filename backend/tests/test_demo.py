from datetime import datetime

import pytest
from sqlalchemy import func, select

pytest.importorskip("PIL")  # Pillow é dependência de desenvolvimento

from searching import relatorios  # noqa: E402
from searching.db.models import Alerta, Coleta, Execucao, HistoricoLink, Produto, RevisaoLink  # noqa: E402
from searching.db.session import criar_engine, iniciar_banco  # noqa: E402
from searching.demo import DIAS, PRODUTOS, gerar_demo  # noqa: E402

HOJE = datetime(2026, 10, 23, 15, 0)


@pytest.fixture
def demo(tmp_path):
    db, prints = tmp_path / "demo.db", tmp_path / "prints"
    resumo = gerar_demo(db, prints, hoje=HOJE)
    with iniciar_banco(criar_engine(db))() as s:
        yield resumo, s, prints


def test_gera_historico_de_14_dias_com_todos_os_cenarios(demo):
    resumo, s, _ = demo
    assert resumo["produtos"] == len(PRODUTOS) and resumo["execucoes"] == DIAS
    status = {r[0] for r in s.execute(select(Coleta.status).distinct())}
    assert {"OK", "BLOQUEIO", "SUSPEITO", "LINK_QUEBRADO"} <= status
    assert s.scalar(select(func.count()).select_from(RevisaoLink).where(RevisaoLink.estado == "pendente")) == 1
    assert [h.origem for h in s.scalars(select(HistoricoLink))] == ["automatico"]
    sucessos = [a.sucesso for a in s.scalars(select(Alerta).order_by(Alerta.id))]
    assert sorted(sucessos) == [False, True]
    assert s.scalar(select(func.sum(Execucao.links_corrigidos))) == 1


def test_e_deterministico_e_nao_mistura_dados_reais(tmp_path):
    a = gerar_demo(tmp_path / "a.db", tmp_path / "pa", hoje=HOJE)
    b = gerar_demo(tmp_path / "b.db", tmp_path / "pb", hoje=HOJE)
    assert a == b
    with iniciar_banco(criar_engine(tmp_path / "a.db"))() as s:
        assert {p.loja for p in s.scalars(select(Produto))} == {"Loja Demo"}
        assert all("example" in p.url_atual for p in s.scalars(select(Produto)))  # nenhum endereço de loja real


def test_prints_existem_e_aparecem_na_galeria_com_preco(demo):
    resumo, s, prints = demo
    arquivos = list(prints.rglob("*.png"))
    assert len(arquivos) == resumo["prints"] > 0
    datas = relatorios.datas_com_prints(s)
    assert len(datas) == 3  # prints só nos últimos 3 dias
    itens = relatorios.galeria(s, data=datas[0]["data"])
    assert itens and all(i["print_url"].startswith("/api/prints/") for i in itens)
    assert any(i["pix"] for i in itens)


def test_painel_de_saude_com_dados_da_demo(demo):
    _, s, _ = demo
    r = relatorios.saude(s, agora=HOJE)
    loja = r["lojas"][0]
    assert loja["loja"] == "Loja Demo" and 80 <= loja["taxa_sucesso"] < 100
    assert r["links_em_revisao"] == 1 and r["alertas"] == {"enviados": 1, "falhos": 1}
    assert "BLOQUEIO" in r["falhas_por_status"]


def test_recriar_substitui_o_banco_anterior(tmp_path):
    db, prints = tmp_path / "demo.db", tmp_path / "prints"
    gerar_demo(db, prints, hoje=HOJE)
    gerar_demo(db, prints, hoje=HOJE)
    with iniciar_banco(criar_engine(db))() as s:
        assert s.scalar(select(func.count()).select_from(Produto)) == len(PRODUTOS)
