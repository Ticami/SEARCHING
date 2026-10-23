"""Senhas (Argon2id), política mínima e geração de segredos aleatórios."""
import hashlib
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_hasher = PasswordHasher()
MIN_SENHA = 12
_COMUNS = {"123456789012", "password1234", "senha1234567", "qwertyuiop12", "administrador", "000000000000", "111111111111"}


class SenhaFraca(ValueError):
    pass


def validar_politica(senha: str, email: str = "") -> None:
    if len(senha) < MIN_SENHA:
        raise SenhaFraca(f"A senha precisa ter pelo menos {MIN_SENHA} caracteres.")
    if len(senha) > 256:
        raise SenhaFraca("A senha é longa demais.")
    baixa = senha.lower()
    if baixa in _COMUNS or len(set(senha)) < 4:
        raise SenhaFraca("Escolha uma senha menos previsível.")
    if email and (baixa == email.lower() or baixa == email.split("@")[0].lower()):
        raise SenhaFraca("A senha não pode ser igual ao e-mail.")


def gerar_hash(senha: str) -> str:
    return _hasher.hash(senha)


def conferir(senha: str, hash_: str) -> bool:
    try:
        return _hasher.verify(hash_, senha)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def precisa_novo_hash(hash_: str) -> bool:
    return _hasher.check_needs_rehash(hash_)


# Hash de uma senha qualquer, usado para gastar o mesmo tempo quando o e-mail não existe (evita enumerar contas).
HASH_FALSO = _hasher.hash("senha-que-nunca-sera-usada")


def novo_segredo(bytes_: int = 32) -> str:
    return secrets.token_urlsafe(bytes_)


def sha256(valor: str) -> str:
    return hashlib.sha256(valor.encode()).hexdigest()


def senha_temporaria() -> str:
    return secrets.token_urlsafe(12)
