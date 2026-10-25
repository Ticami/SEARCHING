"""Retenção dos prints: apaga (ou arquiva) prints antigos, porque eles podem mostrar nome/CEP de quem coletou logado na loja.

O histórico de preços fica; só o arquivo do print sai (a coleta passa a não ter `caminho_print`).
Configuração: tabela `configuracoes` (`retencao_prints_dias`, 0 = guardar para sempre) ou a variável SEARCHING_RETENCAO_PRINTS_DIAS.
Se `SEARCHING_PRINTS_ARQUIVO` apontar uma pasta, os prints vão para lá (mesma estrutura de datas) em vez de serem apagados.
"""
import os
import shutil
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .db.models import Coleta, Configuracao
from .db.session import BACKEND_DIR, PRINTS_DIR

CHAVE = "retencao_prints_dias"


def dias_configurados(s: Session) -> int:
    env = os.environ.get("SEARCHING_RETENCAO_PRINTS_DIAS")
    c = s.get(Configuracao, CHAVE)
    try:
        return max(0, int(env if env not in (None, "") else (c.valor if c else 0)))
    except ValueError:
        return 0


def salvar_dias(s: Session, dias: int) -> None:
    if not 0 <= dias <= 3650:
        raise ValueError("Informe de 0 (guardar para sempre) a 3650 dias.")
    s.merge(Configuracao(chave=CHAVE, valor=str(dias)))


def aplicar(
    s: Session, dias: int | None = None, simular: bool = False, prints_dir: Path | None = None,
    arquivo_dir: Path | None = None, agora: datetime | None = None,
) -> dict:
    """Remove/arquiva os prints mais velhos que `dias`. Só mexe em arquivos dentro da pasta de prints."""
    dias = dias_configurados(s) if dias is None else dias
    resultado = {"dias": dias, "removidos": 0, "arquivados": 0, "ausentes": 0, "simulacao": simular}
    if dias <= 0:
        return resultado
    prints_dir = Path(prints_dir or PRINTS_DIR).resolve()
    destino_env = os.environ.get("SEARCHING_PRINTS_ARQUIVO")
    arquivo_dir = Path(arquivo_dir) if arquivo_dir else (Path(destino_env) if destino_env else None)
    corte = (agora or datetime.now()) - timedelta(days=dias)
    for c in s.scalars(select(Coleta).where(Coleta.caminho_print.is_not(None), Coleta.coletado_em < corte)):
        origem = Path(c.caminho_print)
        origem = (origem if origem.is_absolute() else BACKEND_DIR / origem).resolve()
        if prints_dir not in origem.parents:  # nunca toca em arquivo fora da pasta de prints
            continue
        if not origem.is_file():
            resultado["ausentes"] += 1
        elif arquivo_dir is not None:
            if not simular:
                alvo = arquivo_dir / origem.relative_to(prints_dir)
                alvo.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(origem), alvo)
            resultado["arquivados"] += 1
        else:
            if not simular:
                origem.unlink()
            resultado["removidos"] += 1
        if not simular:
            c.caminho_print = None
    if not simular:
        s.commit()
        for pasta in sorted(prints_dir.glob("*"), reverse=True):  # tira pastas de data que ficaram vazias
            if pasta.is_dir() and not any(pasta.iterdir()):
                pasta.rmdir()
    return resultado
