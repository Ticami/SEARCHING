"""Operação: backup, restauração e migração SQLite -> PostgreSQL.

Uso (a partir de backend/):
  python -m searching.operacao backup [--destino PASTA]
  python -m searching.operacao restaurar ARQUIVO.zip --confirmar
  python -m searching.operacao migrar-banco --destino postgresql://usuario@host/banco [--origem CAMINHO.db]

O backup (SQLite) é um .zip com uma cópia consistente do banco (`searching.db`, feita pela API de backup do SQLite, segura com o
servidor ligado), todos os prints e um `manifesto.json`. Com PostgreSQL, faça o backup do banco com `pg_dump` (veja
docs/IMPLANTACAO.md); este comando cobre os prints também, com `backup --so-prints`.
"""
import argparse
import json
import shutil
import sqlite3
import sys
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine, func, insert, select, text

from .db.models import Base
from .db.session import BACKEND_DIR, PRINTS_DIR, caminho_db, criar_engine, iniciar_banco, url_banco_externo

VERSAO_FORMATO = 1


class ErroOperacao(Exception):
    pass


def _banco_sqlite() -> Path:
    if url_banco_externo():
        raise ErroOperacao(
            "O banco é externo (SEARCHING_DATABASE_URL). Use pg_dump/pg_restore para o banco; "
            "este comando só copia o SQLite local (e, com --so-prints, os prints)."
        )
    return caminho_db()


def _copiar_sqlite(origem: Path, destino: Path) -> None:
    """Cópia consistente mesmo com o servidor escrevendo no banco."""
    com_origem, com_destino = sqlite3.connect(origem), sqlite3.connect(destino)
    try:
        with com_destino:
            com_origem.backup(com_destino)
    finally:
        com_origem.close()
        com_destino.close()


def backup(destino_dir: Path | None = None, so_prints: bool = False, prints_dir: Path | None = None, agora: datetime | None = None) -> Path:
    agora = agora or datetime.now()
    prints_dir = Path(prints_dir or PRINTS_DIR)
    destino_dir = Path(destino_dir or BACKEND_DIR / "backups")
    destino_dir.mkdir(parents=True, exist_ok=True)
    arquivo = destino_dir / f"searching-backup-{agora:%Y%m%d-%H%M%S}.zip"
    with tempfile.TemporaryDirectory() as tmp, zipfile.ZipFile(arquivo, "w", zipfile.ZIP_DEFLATED) as z:
        manifesto = {"formato": VERSAO_FORMATO, "criado_em": agora.isoformat(timespec="seconds"), "banco": None, "prints": 0}
        if not so_prints:
            copia = Path(tmp) / "searching.db"
            _copiar_sqlite(_banco_sqlite(), copia)
            z.write(copia, "searching.db")
            manifesto["banco"] = "sqlite"
        if prints_dir.is_dir():
            for p in sorted(prints_dir.rglob("*")):
                if p.is_file():
                    z.write(p, "prints/" + p.relative_to(prints_dir).as_posix())
                    manifesto["prints"] += 1
        z.writestr("manifesto.json", json.dumps(manifesto, indent=2))
    return arquivo


def _caminho_seguro(base: Path, nome: str) -> Path:
    """Evita 'zip slip': nenhum item do pacote pode escrever fora da pasta de destino."""
    alvo = (base / nome).resolve()
    if base.resolve() not in alvo.parents and alvo != base.resolve():
        raise ErroOperacao(f"Pacote com caminho suspeito: {nome!r}")
    return alvo


def restaurar(arquivo: Path, confirmar: bool = False, prints_dir: Path | None = None, agora: datetime | None = None) -> dict:
    """Restaura banco e prints de um backup. O banco atual NÃO é apagado: vira `<nome>.antes-<data>`."""
    agora = agora or datetime.now()
    prints_dir = Path(prints_dir or PRINTS_DIR)
    if not confirmar:
        raise ErroOperacao("Restaurar substitui o banco atual (uma cópia dele é guardada). Repita com --confirmar.")
    with zipfile.ZipFile(arquivo) as z:
        nomes = z.namelist()
        if "manifesto.json" not in nomes:
            raise ErroOperacao("Este arquivo não parece um backup do SEARCHING (falta manifesto.json).")
        manifesto = json.loads(z.read("manifesto.json"))
        for n in nomes:
            _caminho_seguro(prints_dir if n.startswith("prints/") else BACKEND_DIR, n[len("prints/"):] if n.startswith("prints/") else n)
        guardado = None
        if "searching.db" in nomes:
            destino = _banco_sqlite()
            if destino.exists():
                guardado = destino.with_name(f"{destino.name}.antes-{agora:%Y%m%d-%H%M%S}")
                try:
                    shutil.move(destino, guardado)
                except PermissionError:
                    raise ErroOperacao("O banco está em uso: pare o servidor (e qualquer coleta) antes de restaurar.") from None
            destino.parent.mkdir(parents=True, exist_ok=True)
            with z.open("searching.db") as origem, open(destino, "wb") as saida:
                shutil.copyfileobj(origem, saida)
        n_prints = 0
        for n in nomes:
            if n.startswith("prints/") and not n.endswith("/"):
                alvo = _caminho_seguro(prints_dir, n[len("prints/"):])
                alvo.parent.mkdir(parents=True, exist_ok=True)
                with z.open(n) as origem, open(alvo, "wb") as saida:
                    shutil.copyfileobj(origem, saida)
                n_prints += 1
    return {"manifesto": manifesto, "banco_anterior": str(guardado) if guardado else None, "prints_restaurados": n_prints}


def migrar_banco(url_destino: str, origem: Path | None = None) -> dict[str, int]:
    """Copia todas as tabelas do SQLite para outro banco (PostgreSQL). O destino precisa estar vazio."""
    origem_engine = criar_engine(origem) if origem else criar_engine()
    destino_engine = create_engine(url_destino, pool_pre_ping=True)
    iniciar_banco(destino_engine)
    copiados: dict[str, int] = {}
    with origem_engine.connect() as de, destino_engine.begin() as para:
        for tabela in Base.metadata.sorted_tables:
            # configuracoes é semeada pelo iniciar_banco; as demais tabelas precisam estar vazias
            if tabela.name != "configuracoes" and para.scalar(select(func.count()).select_from(tabela)):
                raise ErroOperacao(f"O destino não está vazio (tabela {tabela.name}). Use um banco novo.")
        for tabela in Base.metadata.sorted_tables:
            linhas = [dict(r._mapping) for r in de.execute(select(tabela))]
            if tabela.name == "configuracoes":
                para.execute(tabela.delete())
            if linhas:
                para.execute(insert(tabela), linhas)
            copiados[tabela.name] = len(linhas)
        if destino_engine.dialect.name == "postgresql":  # ids foram inseridos explicitamente: realinha as sequências
            for tabela in Base.metadata.sorted_tables:
                if "id" in tabela.c and tabela.c.id.primary_key:
                    para.execute(text(
                        f"SELECT setval(pg_get_serial_sequence('\"{tabela.name}\"', 'id'), COALESCE((SELECT MAX(id) FROM \"{tabela.name}\"), 1))"
                    ))
    return copiados


def main(argv: list[str] | None = None, saida=print) -> int:
    ap = argparse.ArgumentParser(prog="searching.operacao", description="Backup, restauração e migração do SEARCHING.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("backup")
    b.add_argument("--destino", type=Path)
    b.add_argument("--so-prints", action="store_true")
    r = sub.add_parser("restaurar")
    r.add_argument("arquivo", type=Path)
    r.add_argument("--confirmar", action="store_true")
    ret = sub.add_parser("reter-prints", help="apaga (ou arquiva) prints mais antigos que N dias")
    ret.add_argument("--dias", type=int, help="padrão: o configurado (0 = não faz nada)")
    ret.add_argument("--simular", action="store_true")
    m = sub.add_parser("migrar-banco")
    m.add_argument("--destino", required=True)
    m.add_argument("--origem", type=Path)
    args = ap.parse_args(argv)
    try:
        if args.cmd == "backup":
            saida(f"Backup criado: {backup(args.destino, args.so_prints)}")
        elif args.cmd == "restaurar":
            res = restaurar(args.arquivo, args.confirmar)
            saida(f"Restaurado ({res['prints_restaurados']} prints). Banco anterior guardado em: {res['banco_anterior'] or 'não havia'}")
        elif args.cmd == "reter-prints":
            from . import retencao

            with iniciar_banco(criar_engine())() as s:
                r = retencao.aplicar(s, args.dias, args.simular)
            saida(f"Retenção de {r['dias']} dia(s){' (simulação)' if r['simulacao'] else ''}: "
                  f"{r['removidos']} removido(s), {r['arquivados']} arquivado(s), {r['ausentes']} já ausente(s).")
        else:
            for tabela, n in migrar_banco(args.destino, args.origem).items():
                saida(f"{tabela}: {n} linha(s)")
            saida("Migração concluída. Aponte SEARCHING_DATABASE_URL para o novo banco.")
        return 0
    except (ErroOperacao, zipfile.BadZipFile, OSError) as e:
        saida(f"Erro: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
