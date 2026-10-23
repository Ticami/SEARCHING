"""Ponto de entrada da coleta, independente do servidor web.

Uso (a partir de backend/):  python -m searching.run [--origem manual|agendada] [--loja X] [--incluir X] [--excluir X]

--origem só marca de onde veio a execução no histórico; use "agendada" se chamar o comando por um agendador seu.
Imprime o resumo em JSON na última linha da saída. Códigos de saída: 0 ok, 2 já há coleta em andamento, 1 erro.
"""
import argparse
import json
import logging
import sys
from logging.handlers import RotatingFileHandler

from .core.coleta import executar_coleta
from .core.trava import ColetaEmAndamento
from .db.migracao_csv import importar_se_vazio
from .db.session import BACKEND_DIR, criar_engine, iniciar_banco


def _configurar_log(nivel: str) -> None:
    pasta = BACKEND_DIR / "logs"
    pasta.mkdir(exist_ok=True)
    handler = RotatingFileHandler(pasta / "searching.log", maxBytes=1_000_000, backupCount=5, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    raiz = logging.getLogger("searching")
    raiz.setLevel(nivel.upper())
    raiz.addHandler(handler)
    raiz.addHandler(logging.StreamHandler(sys.stderr))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="searching.run", description="Coleta os preços dos produtos ativos.")
    ap.add_argument("--origem", choices=["agendada", "manual"], default="manual")
    ap.add_argument("--loja", action="append", default=[], help="filtra por loja (repetível)")
    ap.add_argument("--incluir", action="append", default=[], help="só estes modelos (repetível)")
    ap.add_argument("--excluir", action="append", default=[], help="exceto estes modelos (repetível)")
    ap.add_argument("--log-nivel", default="INFO")
    args = ap.parse_args(argv)

    _configurar_log(args.log_nivel)
    fabrica = iniciar_banco(criar_engine())
    importar_se_vazio(fabrica)

    try:
        resumo = executar_coleta(fabrica, args.origem, args.loja, args.incluir, args.excluir)
    except ColetaEmAndamento as exc:
        print(json.dumps({"erro": str(exc), "em_andamento": True}))
        return 2
    except Exception as exc:
        logging.getLogger("searching").exception("Coleta falhou")
        print(json.dumps({"erro": f"{type(exc).__name__}: {exc}"}))
        return 1

    print(json.dumps(resumo, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
