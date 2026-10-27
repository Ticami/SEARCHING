"""Utilidades compartilhadas pelos blueprints (banco da requisição, corpo JSON, id do usuário)."""
from flask import current_app, g, request

from .. import modo


def fabrica():
    """Fábrica de sessões do banco, guardada em app.config pelo server.py."""
    return current_app.config["DB_FABRICA"]


def corpo_json() -> dict:
    return request.get_json(force=True, silent=True) or {}


def uid():
    """Id do usuário logado (None no modo local, que tem uma única sessão de coleta)."""
    return g.usuario.id if modo.hospedado() else None
