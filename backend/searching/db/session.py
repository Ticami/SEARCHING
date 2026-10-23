import os
from pathlib import Path

from sqlalchemy import Engine, create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker

from .models import Base, Configuracao

BACKEND_DIR = Path(__file__).resolve().parents[2]
DB_PADRAO = BACKEND_DIR / "data" / "searching.db"

# Valores padrão do PRD (seção 15); podem ser alterados na tabela configuracoes.
CONFIG_PADRAO = {
    "horario_coleta": "12:00",
    "alerta_base_preco": "pix",
    "alerta_base_comparacao": "ultimo",
    "alerta_pct_queda": "5",
    "alerta_degrau_pct": "2",
    "confianca_minima_autocorrecao": "0.90",
    "variacao_suspeita_pct": "40",
    "retentativas": "2",
    "buscas_por_produto_dia": "1",
}


def caminho_db() -> Path:
    return Path(os.environ.get("SEARCHING_DB", DB_PADRAO))


def criar_engine(caminho: str | Path | None = None) -> Engine:
    destino = Path(caminho) if caminho else caminho_db()
    if str(destino) != ":memory:":
        destino.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{destino}")

    @event.listens_for(engine, "connect")
    def _pragmas(conn, _):
        conn.execute("PRAGMA foreign_keys=ON")

    return engine


def iniciar_banco(engine: Engine) -> sessionmaker[Session]:
    """Cria as tabelas (se faltarem) e semeia as configurações padrão sem sobrescrever as existentes."""
    Base.metadata.create_all(engine)
    fabrica = sessionmaker(engine, expire_on_commit=False)
    with fabrica() as s:
        existentes = set(s.scalars(select(Configuracao.chave)))
        for chave, valor in CONFIG_PADRAO.items():
            if chave not in existentes:
                s.add(Configuracao(chave=chave, valor=valor))
        s.commit()
    return fabrica
