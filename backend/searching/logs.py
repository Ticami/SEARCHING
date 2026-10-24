"""Logs estruturados (uma linha JSON por evento) e registro de cada requisição, com id para rastrear.

SEARCHING_LOG_FORMATO=json|texto (padrão: json no modo hospedado, texto no local). SEARCHING_LOG_NIVEL muda o nível (INFO).
Nunca registra corpo de requisição, cookies, tokens nem a query string (links de redefinição levam token nela).
"""
import json
import logging
import os
import sys
import time
import uuid
from datetime import datetime, timezone

from flask import g, request

from . import modo

_RESERVADOS = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message", "asctime"}


class FormatoJson(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        linha = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="milliseconds"),
            "nivel": record.levelname, "logger": record.name, "msg": record.getMessage(),
        }
        linha.update({k: v for k, v in record.__dict__.items() if k not in _RESERVADOS and not k.startswith("_")})
        if record.exc_info:
            linha["excecao"] = self.formatException(record.exc_info)
        return json.dumps(linha, ensure_ascii=False, default=str)


def configurar(fluxo=None) -> logging.Logger:
    """Liga o logger "searching" (idempotente). Devolve-o."""
    raiz = logging.getLogger("searching")
    raiz.setLevel((os.environ.get("SEARCHING_LOG_NIVEL") or "INFO").upper())
    formato = (os.environ.get("SEARCHING_LOG_FORMATO") or ("json" if modo.hospedado() else "texto")).lower()
    for h in [h for h in raiz.handlers if getattr(h, "_searching", False)]:
        raiz.removeHandler(h)
    handler = logging.StreamHandler(fluxo or sys.stdout)
    handler._searching = True
    handler.setFormatter(FormatoJson() if formato == "json" else logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    raiz.addHandler(handler)
    raiz.propagate = False
    return raiz


def instalar(app) -> None:
    """Registra uma linha por requisição: método, caminho, status, duração, usuário e id (devolvido em X-Request-ID)."""
    log = logging.getLogger("searching.http")

    @app.before_request
    def _inicio():
        g.inicio = time.perf_counter()
        g.request_id = (request.headers.get("X-Request-ID") or uuid.uuid4().hex)[:64]

    @app.after_request
    def _fim(resposta):
        rid = getattr(g, "request_id", None)
        if rid:
            resposta.headers["X-Request-ID"] = rid
        if request.path != "/api/health":  # o health check do orquestrador não polui o log
            usuario = getattr(g, "usuario", None)
            log.info(
                "requisição", extra={
                    "request_id": rid, "metodo": request.method, "caminho": request.path, "status": resposta.status_code,
                    "ms": round((time.perf_counter() - getattr(g, "inicio", time.perf_counter())) * 1000, 1),
                    "usuario_id": getattr(usuario, "id", None), "ip": request.remote_addr,
                },
            )
        return resposta
