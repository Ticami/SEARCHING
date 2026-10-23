"""2FA por TOTP (RFC 6238), sem dependências: compatível com Google Authenticator, Authy, 1Password etc."""
import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote


def novo_segredo() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _codigo(segredo: str, contador: int) -> str:
    chave = base64.b32decode(segredo + "=" * (-len(segredo) % 8), casefold=True)
    h = hmac.new(chave, struct.pack(">Q", contador), hashlib.sha1).digest()
    i = h[-1] & 0x0F
    return f"{(struct.unpack('>I', h[i:i + 4])[0] & 0x7FFFFFFF) % 1_000_000:06d}"


def codigo_atual(segredo: str, agora: float | None = None) -> str:
    return _codigo(segredo, int((time.time() if agora is None else agora) // 30))


def verificar(segredo: str, codigo: str, agora: float | None = None, janela: int = 1) -> bool:
    codigo = (codigo or "").replace(" ", "")
    if not (len(codigo) == 6 and codigo.isdigit()):
        return False
    passo = int((time.time() if agora is None else agora) // 30)
    return any(hmac.compare_digest(_codigo(segredo, passo + d), codigo) for d in range(-janela, janela + 1))


def uri(segredo: str, email: str, emissor: str = "SEARCHING") -> str:
    return f"otpauth://totp/{quote(emissor)}:{quote(email)}?secret={segredo}&issuer={quote(emissor)}&digits=6&period=30"
