"""Operação: backup/restauração, migração de banco, URL do PostgreSQL e logs estruturados."""
import io
import json
import logging
import zipfile

import pytest
from conftest import URL_S25
from sqlalchemy import func, select

from searching import logs, operacao
from searching.db import links
from searching.db.models import Produto
from searching.db.session import criar_engine, iniciar_banco, url_banco_externo


@pytest.fixture
def ambiente(tmp_path, monkeypatch):
    monkeypatch.setenv("SEARCHING_DB", str(tmp_path / "dados" / "searching.db"))
    monkeypatch.delenv("SEARCHING_DATABASE_URL", raising=False)
    prints = tmp_path / "prints"
    (prints / "2026-01-01").mkdir(parents=True)
    (prints / "2026-01-01" / "a.png").write_bytes(b"\x89PNG\r\n\x1a\nconteudo")
    fabrica = iniciar_banco(criar_engine())
    with fabrica() as s:
        links.criar(s, "Samsung Galaxy S25 256GB", URL_S25, "Magazine Luiza")
        s.commit()
    return fabrica, prints


def test_backup_e_restauracao_devolvem_banco_e_prints(ambiente, tmp_path):
    fabrica, prints = ambiente
    pacote = operacao.backup(tmp_path / "bk", prints_dir=prints)
    with zipfile.ZipFile(pacote) as z:
        assert {"searching.db", "manifesto.json", "prints/2026-01-01/a.png"} <= set(z.namelist())
        assert json.loads(z.read("manifesto.json"))["prints"] == 1

    # desastre: apaga um produto e um print
    with fabrica() as s:
        for p in s.scalars(select(Produto)):
            s.delete(p)
        s.commit()
    fabrica.kw["bind"].dispose()  # o servidor precisa estar parado para restaurar (no Windows o arquivo fica travado)
    (prints / "2026-01-01" / "a.png").unlink()

    with pytest.raises(operacao.ErroOperacao, match="--confirmar"):
        operacao.restaurar(pacote, prints_dir=prints)
    res = operacao.restaurar(pacote, confirmar=True, prints_dir=prints)
    assert res["prints_restaurados"] == 1 and res["banco_anterior"]
    assert (prints / "2026-01-01" / "a.png").read_bytes().endswith(b"conteudo")
    with iniciar_banco(criar_engine())() as s:
        assert s.scalar(select(func.count()).select_from(Produto)) == 1
    from pathlib import Path

    assert Path(res["banco_anterior"]).exists()  # o banco antes da restauração não foi destruído


def test_restaurar_recusa_pacote_com_caminho_perigoso(ambiente, tmp_path):
    _, prints = ambiente
    ruim = tmp_path / "ruim.zip"
    with zipfile.ZipFile(ruim, "w") as z:
        z.writestr("manifesto.json", json.dumps({"formato": 1}))
        z.writestr("prints/../../fora.txt", "x")
    with pytest.raises(operacao.ErroOperacao, match="suspeito"):
        operacao.restaurar(ruim, confirmar=True, prints_dir=prints)
    assert not (tmp_path / "fora.txt").exists()
    nao_backup = tmp_path / "x.zip"
    with zipfile.ZipFile(nao_backup, "w") as z:
        z.writestr("qualquer.txt", "x")
    with pytest.raises(operacao.ErroOperacao, match="manifesto"):
        operacao.restaurar(nao_backup, confirmar=True, prints_dir=prints)


def test_backup_com_banco_externo_explica_o_caminho(ambiente, monkeypatch, tmp_path):
    _, prints = ambiente
    monkeypatch.setenv("SEARCHING_DATABASE_URL", "postgresql://u@h/b")
    with pytest.raises(operacao.ErroOperacao, match="pg_dump"):
        operacao.backup(tmp_path / "bk", prints_dir=prints)
    assert operacao.backup(tmp_path / "bk", so_prints=True, prints_dir=prints).exists()  # prints continuam cobertos


def test_migrar_banco_copia_todas_as_tabelas(ambiente, tmp_path):
    fabrica, _ = ambiente
    from searching.auth import servico

    with fabrica() as s:
        servico.criar_usuario(s, "a@b.com", "A", "admin", "Senha-Forte-123")
        s.commit()
    destino = f"sqlite:///{tmp_path / 'novo.db'}"
    copiados = operacao.migrar_banco(destino)
    assert copiados["produtos"] == 1 and copiados["usuarios"] == 1
    with pytest.raises(operacao.ErroOperacao, match="não está vazio"):
        operacao.migrar_banco(destino)
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    with Session(create_engine(destino)) as s:
        assert s.scalar(select(Produto.nome_comercial)) == "Samsung Galaxy S25 256GB"


def test_url_do_postgres_vira_driver_psycopg(monkeypatch):
    monkeypatch.setenv("SEARCHING_DATABASE_URL", "postgres://u:p@host:5432/db")
    assert url_banco_externo() == "postgresql+psycopg://u:p@host:5432/db"
    monkeypatch.setenv("SEARCHING_DATABASE_URL", "postgresql://u@host/db")
    assert url_banco_externo() == "postgresql+psycopg://u@host/db"
    monkeypatch.delenv("SEARCHING_DATABASE_URL")
    assert url_banco_externo() is None


def test_formato_json_dos_logs(monkeypatch):
    monkeypatch.setenv("SEARCHING_LOG_FORMATO", "json")
    fluxo = io.StringIO()
    log = logs.configurar(fluxo)
    log.propagate = False
    logging.getLogger("searching.teste").warning("algo", extra={"produto_id": 7})
    linha = json.loads(fluxo.getvalue().strip().splitlines()[-1])
    assert linha["msg"] == "algo" and linha["produto_id"] == 7 and linha["nivel"] == "WARNING" and "ts" in linha


def test_requisicoes_viram_logs_sem_vazar_query_nem_corpo(hosp):
    fluxo = io.StringIO()
    logs.configurar(fluxo)
    c = hosp.cliente("admin@teste.com")
    r = c.get("/api/links?token=SEGREDO123", headers={"X-Request-ID": "abc-123"})
    assert r.headers["X-Request-ID"] == "abc-123"
    c.login("admin@teste.com", "senha-errada-xxxx")
    saida = fluxo.getvalue()
    assert "SEGREDO123" not in saida and "senha-errada-xxxx" not in saida
    eventos = [json.loads(linha) for linha in saida.splitlines() if linha.startswith("{")]
    achado = next(e for e in eventos if e.get("request_id") == "abc-123")
    assert achado["caminho"] == "/api/links" and achado["status"] == 200 and achado["usuario_id"] == hosp.uid("admin@teste.com")
    assert any(e.get("caminho") == "/api/auth/login" and e.get("status") == 401 for e in eventos)


def test_cli_de_backup(ambiente, tmp_path):
    saidas = []
    assert operacao.main(["backup", "--destino", str(tmp_path / "bk2")], saida=saidas.append) == 0
    assert "Backup criado" in saidas[0]
    assert operacao.main(["restaurar", str(tmp_path / "nao-existe.zip"), "--confirmar"], saida=saidas.append) == 1
