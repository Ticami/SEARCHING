"""Quem recebe os e-mails: lista editável pela interface (admin) + assinantes de cada produto.

A senha do SMTP continua só no .env. Se a lista da interface estiver vazia, vale ALERTA_DESTINATARIOS do .env (como sempre foi).
"""
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import Assinatura, Configuracao, Usuario

CHAVE = "alerta_destinatarios"
MAX_DESTINATARIOS = 20
_EMAIL = re.compile(r"^[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+$")


def validar_lista(valores) -> list[str]:
    """Aceita lista ou texto separado por vírgula/;/quebra de linha. Lança ValueError com a mensagem para o usuário."""
    if isinstance(valores, str):
        valores = re.split(r"[,;\n]+", valores)
    limpos: list[str] = []
    for v in valores or []:
        e = str(v).strip().lower()
        if not e:
            continue
        if not _EMAIL.match(e) or len(e) > 200:
            raise ValueError(f"E-mail inválido: {v}")
        if e not in limpos:
            limpos.append(e)
    if len(limpos) > MAX_DESTINATARIOS:
        raise ValueError(f"No máximo {MAX_DESTINATARIOS} destinatários")
    return limpos


def configurados(s: Session) -> list[str]:
    c = s.get(Configuracao, CHAVE)
    return [e for e in (c.valor if c else "").split(",") if e]


def salvar(s: Session, valores) -> list[str]:
    lista = validar_lista(valores)
    s.merge(Configuracao(chave=CHAVE, valor=",".join(lista)))
    s.flush()
    return lista


def assinantes(s: Session, produto_id: int) -> list[str]:
    return list(s.scalars(
        select(Usuario.email).join(Assinatura, Assinatura.usuario_id == Usuario.id)
        .where(Assinatura.produto_id == produto_id, Usuario.ativo.is_(True)).order_by(Usuario.email)
    ))


def efetivos(s: Session, do_env, produto_id: int | None = None) -> tuple[str, ...]:
    """Lista da interface (ou a do .env, se vazia) + quem assinou o produto. Sem repetidos."""
    lista = list(configurados(s) or do_env)
    if produto_id is not None:
        lista += assinantes(s, produto_id)
    vistos: list[str] = []
    for e in lista:
        if e.lower() not in (v.lower() for v in vistos):
            vistos.append(e)
    return tuple(vistos)
