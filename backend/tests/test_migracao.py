from sqlalchemy import func, select

from searching.db.migracao_csv import migrar
from searching.db.models import Coleta, Configuracao, Execucao, Produto
from searching.db.session import criar_engine, iniciar_banco

LINKS = """NOME COMERCIAL;LINK;LOJA
Samsung Galaxy S25 256GB;https://exemplo.com/s25;Magazine Luiza
Samsung Galaxy A17 5G 128GB;https://exemplo.com/a17;Magazine Luiza
Samsung Galaxy A17 5G 128GB;https://exemplo.com/a17;Magazine Luiza
"""

HISTORICO = """DATA;NOME;MODELO;SITE;ENTREGUE_POR;PIX;STATUS;LINK;PARCELADO
2025-12-08 16:19:12;Samsung Galaxy S25 256GB;Celular S25;Magazine Luiza;Samsung;R$ 3.799 , 00;OK;https://exemplo.com/s25;R$ 3.998,95
2025-12-08 16:19:16;Samsung Galaxy A17 5G 128GB;Celular A17;Magazine Luiza;Samsung;R$ 1.199 , 00;OK;https://exemplo.com/a17;R$ 1.332,22
2025-12-09 22:47:04;Samsung Galaxy S25 256GB;;Magazine Luiza;;;OK;https://exemplo.com/s25;
2026-02-24 11:20:33;Samsung Galaxy S25 256GB;;Magazine Luiza;N/A;N/A;OK;https://exemplo.com/s25;N/A
2026-02-25 09:00:00;Samsung Galaxy Antigo 64GB;;Magazine Luiza;Samsung;R$ 500,00;OK;https://exemplo.com/antigo;
"""


def _arquivos(tmp_path):
    links, hist = tmp_path / "links.csv", tmp_path / "historico.csv"
    links.write_text(LINKS, encoding="utf-8-sig")
    hist.write_text(HISTORICO, encoding="utf-8-sig")
    return links, hist, tmp_path / "t.db"


def test_migracao_converte_precos_e_corrige_status(tmp_path):
    links, hist, db = _arquivos(tmp_path)
    resumo = migrar(links, hist, db, prints_dir=tmp_path / "prints")

    assert resumo["links"] == {"criados": 2, "existentes": 0, "duplicados_no_csv": 1}
    assert resumo["historico"]["coletas"] == 5
    assert resumo["historico"]["produtos_criados"] == 1

    with iniciar_banco(criar_engine(db))() as s:
        s25 = s.scalar(select(Produto).where(Produto.nome_comercial == "Samsung Galaxy S25 256GB"))
        primeira = s.scalars(select(Coleta).where(Coleta.produto_id == s25.id).order_by(Coleta.coletado_em)).first()
        assert primeira.preco_pix_centavos == 379900
        assert primeira.preco_cartao_1x_centavos == 399895
        assert primeira.texto_bruto["pix"] == "R$ 3.799 , 00"

        # Nenhuma coleta OK pode ficar sem preço.
        sem_preco_ok = s.scalar(
            select(func.count()).select_from(Coleta).where(Coleta.status == "OK", Coleta.preco_pix_centavos.is_(None))
        )
        assert sem_preco_ok == 0
        assert s.scalar(select(func.count()).select_from(Coleta).where(Coleta.status == "PRECO_NAO_ENCONTRADO")) == 2

        antigo = s.scalar(select(Produto).where(Produto.nome_comercial == "Samsung Galaxy Antigo 64GB"))
        assert antigo.ativo is False
        assert s.get(Configuracao, "alerta_pct_queda").valor == "5"


def test_migracao_e_idempotente(tmp_path):
    links, hist, db = _arquivos(tmp_path)
    migrar(links, hist, db, prints_dir=tmp_path / "prints")
    segunda = migrar(links, hist, db, prints_dir=tmp_path / "prints")

    assert segunda["links"]["criados"] == 0
    assert segunda["historico"]["coletas"] == 0
    assert segunda["historico"]["ja_importadas"] == 5

    with iniciar_banco(criar_engine(db))() as s:
        assert s.scalar(select(func.count()).select_from(Coleta)) == 5
        assert s.scalar(select(func.count()).select_from(Produto)) == 3
        execs = s.scalars(select(Execucao).order_by(Execucao.iniciada_em)).all()
        assert [e.total for e in execs] == [2, 1, 1, 1]
        assert all(e.origem == "legado" for e in execs)


def test_prints_antigos_sao_vinculados_as_coletas_certas(tmp_path):
    links, hist, db = _arquivos(tmp_path)
    pasta = tmp_path / "prints" / "2025-12-08_16-19-01"
    pasta.mkdir(parents=True)
    # print tirado 2 s antes da coleta do S25 (16:19:12) e outro do A17 (16:19:16)
    for nome in ("Samsung Galaxy S25 256GB_16-19-10.png", "Samsung Galaxy A17 5G 128GB_16-19-14.png", "Modelo Desconhecido_16-19-10.png", "lixo.txt"):
        (pasta / nome).write_bytes(b"png")

    resumo = migrar(links, hist, db, prints_dir=tmp_path / "prints")
    assert resumo["prints_vinculados"] == 2

    with iniciar_banco(criar_engine(db))() as s:
        por_produto = {c.produto.nome_comercial: c.caminho_print for c in s.scalars(select(Coleta)) if c.caminho_print}
        assert por_produto == {
            "Samsung Galaxy S25 256GB": "prints/2025-12-08_16-19-01/Samsung Galaxy S25 256GB_16-19-10.png",
            "Samsung Galaxy A17 5G 128GB": "prints/2025-12-08_16-19-01/Samsung Galaxy A17 5G 128GB_16-19-14.png",
        }
    assert migrar(links, hist, db, prints_dir=tmp_path / "prints")["prints_vinculados"] == 0  # idempotente
