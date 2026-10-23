import os
from pathlib import Path

from sqlalchemy import Engine, create_engine, event, inspect, select, text
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
    "timeout_produto_s": "30",
    "espera_retentativa_s": "15",
    # Ritmo lento de propósito: as lojas bloqueiam acessos rápidos como se fossem robôs.
    "pausa_min_s": "20",
    "pausa_max_s": "45",
    "bloqueios_para_interromper": "2",
    "recuperacao_automatica": "1",
    "alertas_ativos": "1",
    "alerta_dias_janela": "30",
    "resumo_diario_email": "0",
    "navegador_headless": "0",
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


def _adicionar_colunas_novas(engine: Engine) -> None:
    """create_all não altera tabelas existentes: acrescenta colunas que o modelo ganhou depois."""
    inspetor = inspect(engine)
    with engine.begin() as conn:
        for tabela in Base.metadata.sorted_tables:
            if not inspetor.has_table(tabela.name):
                continue
            existentes = {c["name"] for c in inspetor.get_columns(tabela.name)}
            for coluna in tabela.columns:
                if coluna.name not in existentes:
                    tipo = coluna.type.compile(engine.dialect)
                    conn.execute(text(f'ALTER TABLE "{tabela.name}" ADD COLUMN "{coluna.name}" {tipo}'))


def iniciar_banco(engine: Engine) -> sessionmaker[Session]:
    """Cria as tabelas (se faltarem) e semeia as configurações padrão sem sobrescrever as existentes."""
    Base.metadata.create_all(engine)
    _adicionar_colunas_novas(engine)
    fabrica = sessionmaker(engine, expire_on_commit=False)
    with fabrica() as s:
        existentes = set(s.scalars(select(Configuracao.chave)))
        for chave, valor in CONFIG_PADRAO.items():
            if chave not in existentes:
                s.add(Configuracao(chave=chave, valor=valor))
        s.commit()
    return fabrica
