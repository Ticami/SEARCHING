"""Fixtures do modo hospedado: servidor recarregado com login, três usuários (admin, coletor, leitor) e um cliente HTTP."""
import importlib
import os
import sys
from pathlib import Path

import pytest

ORIGEM = "https://searching.teste"
SENHA = "Senha-Forte-123"
FIXTURES = Path(__file__).parent / "fixtures"
URL_S25 = "https://www.magazineluiza.com.br/celular-samsung-galaxy-s25/p/abc123/te/gs25/"
EXTENSAO = "chrome-extension://abcdefghijklmnopabcdefghijklmnop"


class Cliente:
    """Navegador simulado: guarda o cookie e o token CSRF e manda a Origin do site, como o frontend faz."""

    def __init__(self, server):
        self.c = server.app.test_client()
        self.csrf = None

    def req(self, metodo, url, json=None, headers=None, origem=ORIGEM, **kw):
        h = {}
        if origem:
            h["Origin"] = origem
        if self.csrf and metodo.upper() not in ("GET", "HEAD", "OPTIONS"):
            h["X-CSRF-Token"] = self.csrf
        h.update(headers or {})
        return getattr(self.c, metodo)(url, json=json, headers=h, base_url=ORIGEM, **kw)

    def get(self, url, **kw):
        return self.req("get", url, **kw)

    def post(self, url, json=None, **kw):
        return self.req("post", url, json=json if json is not None else {}, **kw)

    def put(self, url, json=None, **kw):
        return self.req("put", url, json=json if json is not None else {}, **kw)

    def patch(self, url, json=None, **kw):
        return self.req("patch", url, json=json if json is not None else {}, **kw)

    def delete(self, url, json=None, **kw):
        return self.req("delete", url, json=json, **kw)

    def login(self, email, senha=SENHA, codigo=None):
        r = self.post("/api/auth/login", {"email": email, "senha": senha, **({"codigo": codigo} if codigo else {})})
        if r.status_code == 200:
            self.csrf = r.get_json()["csrf"]
        return r


class Hospedado:
    def __init__(self, server, tmp_path):
        self.server = server
        self.fabrica = server.db_fabrica
        self.emails = []
        self.tmp_path = tmp_path
        from searching.auth import servico

        with self.fabrica() as s:
            for email, papel in (("admin@teste.com", "admin"), ("coletor@teste.com", "coletor"),
                                 ("coletor2@teste.com", "coletor"), ("leitor@teste.com", "leitor")):
                servico.criar_usuario(s, email, email.split("@")[0], papel, SENHA)
            s.commit()

    def cliente(self, email=None):
        c = Cliente(self.server)
        if email:
            assert c.login(email).status_code == 200, email
        return c

    def uid(self, email):
        from sqlalchemy import select

        from searching.db.models import Usuario

        with self.fabrica() as s:
            return s.scalar(select(Usuario.id).where(Usuario.email == email))


@pytest.fixture
def hosp(tmp_path, monkeypatch):
    monkeypatch.setenv("SEARCHING_DB", str(tmp_path / "h.db"))
    monkeypatch.setenv("SEARCHING_PRINTS", str(tmp_path / "prints"))
    monkeypatch.setenv("SEARCHING_MODO", "hospedado")
    monkeypatch.setenv("SEARCHING_2FA_ADMIN", "0")  # os testes de 2FA obrigatório ligam de volta
    monkeypatch.setenv("SEARCHING_URL_PUBLICA", ORIGEM)
    if os.environ.get("SEARCHING_TESTE_PG"):  # roda a suíte hospedada num PostgreSQL de verdade (banco zerado a cada teste)
        from sqlalchemy import create_engine

        from searching.db.models import Base

        monkeypatch.setenv("SEARCHING_DATABASE_URL", os.environ["SEARCHING_TESTE_PG"])
        motor = create_engine(os.environ["SEARCHING_TESTE_PG"].replace("postgresql://", "postgresql+psycopg://"))
        Base.metadata.drop_all(motor)
        motor.dispose()
    sys.modules.pop("server", None)
    server = importlib.import_module("server")
    h = Hospedado(server, tmp_path)

    # nenhum e-mail real: o Notificador do teste guarda as mensagens
    from types import SimpleNamespace

    smtp = SimpleNamespace(remetente="searching@teste.com", destinatarios=("x@teste.com",))
    server.app.config["NOTIFICADOR"] = type(server.app.config["NOTIFICADOR"])(
        carregar_config=lambda: smtp, enviar=lambda msg, cfg=None: h.emails.append(msg)
    )
    yield h
    sys.modules.pop("server", None)
