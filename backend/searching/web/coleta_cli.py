"""Coleta automática chamada pela API (só modo local): roda `python -m searching.run` num subprocesso."""
import json
import subprocess
import sys
from pathlib import Path

from .. import modo

BACKEND_DIR = Path(__file__).resolve().parents[2]


def rodar_coleta_cli(origem, stores=None, include=None, exclude=None):
    """Executa a coleta automática pelo mesmo comando da linha de comando: python -m searching.run.

    Devolve (codigo_de_saida, resumo_dict). Código 2 = já existe uma coleta em andamento.
    """
    modo.exigir_local("A coleta automática")  # o servidor hospedado nunca abre lojas
    cmd = [sys.executable, "-m", "searching.run", "--origem", origem]
    for flag, valores in (("--loja", stores), ("--incluir", include), ("--excluir", exclude)):
        for v in valores or []:
            cmd.append(f"{flag}={v}")
    proc = subprocess.run(cmd, cwd=BACKEND_DIR, capture_output=True, text=True, encoding="utf-8", errors="replace")
    linhas = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    try:
        resumo = json.loads(linhas[-1]) if linhas else {}
    except ValueError:
        resumo = {"erro": (proc.stderr or proc.stdout or "saída inválida do coletor")[-500:]}
    return proc.returncode, resumo
