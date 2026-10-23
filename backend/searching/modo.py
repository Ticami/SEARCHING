"""Modo de execução: local (padrão, sem login, 127.0.0.1) ou hospedado (login, papéis, coleta só pela extensão)."""
import os
from urllib.parse import urlparse

LOCAL = "local"
HOSPEDADO = "hospedado"


class ModoInvalido(RuntimeError):
    pass


class OperacaoBloqueadaNoModoHospedado(RuntimeError):
    """O servidor hospedado nunca abre lojas por conta própria: quem navega é a extensão, no computador da pessoa."""


def modo(env: dict | None = None) -> str:
    env = os.environ if env is None else env
    valor = (env.get("SEARCHING_MODO") or LOCAL).strip().lower()
    if valor not in (LOCAL, HOSPEDADO):
        raise ModoInvalido(f"SEARCHING_MODO={valor!r} inválido: use 'local' ou 'hospedado'.")
    return valor


def hospedado(env: dict | None = None) -> bool:
    return modo(env) == HOSPEDADO


def exigir_local(o_que: str) -> None:
    """Chamado antes de qualquer coisa que abra uma loja (navegador, coleta automática)."""
    if hospedado():
        raise OperacaoBloqueadaNoModoHospedado(
            f"{o_que} está desativado no modo hospedado: a coleta acontece pela extensão, no computador de cada pessoa."
        )


def url_publica(env: dict | None = None) -> str:
    """URL HTTPS pela qual as pessoas acessam o site (sem barra final). Exigida no modo hospedado."""
    env = os.environ if env is None else env
    url = (env.get("SEARCHING_URL_PUBLICA") or "").strip().rstrip("/")
    p = urlparse(url)
    if not url or not p.hostname:
        raise ModoInvalido("Defina SEARCHING_URL_PUBLICA (ex.: https://searching.suaempresa.com) para o modo hospedado.")
    local = p.hostname in ("localhost", "127.0.0.1", "::1")
    if p.scheme != "https" and not (p.scheme == "http" and local):
        raise ModoInvalido("SEARCHING_URL_PUBLICA precisa ser HTTPS (http só é aceito para localhost, em testes).")
    if p.path not in ("", "/") or p.query:
        raise ModoInvalido("SEARCHING_URL_PUBLICA deve ser só o endereço (sem caminho).")
    return f"{p.scheme}://{p.netloc}"
