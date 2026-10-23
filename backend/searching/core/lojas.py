import re
from urllib.parse import urlparse

_ALIASES = {
    "magalu": "magazine luiza",
    "magazineluiza": "magazine luiza",
    "magazine luiza": "magazine luiza",
    "magazinevoce": "magazine luiza",
    "amazon": "amazon",
    "amazon.com.br": "amazon",
    "casasbahia": "casas bahia",
    "casas bahia": "casas bahia",
}


def normalizar(texto: str) -> str:
    return re.sub(r"\s+", " ", (texto or "")).strip().lower()


def normalizar_loja(texto: str) -> str:
    chave = normalizar(texto)
    return _ALIASES.get(chave, chave)


def loja_do_link(url: str) -> str:
    """Nome da loja inferido pelo domínio do link; vazio se não reconhecida."""
    host = (urlparse(url or "").hostname or "").lower()
    if "magazineluiza" in host or "magalu" in host or "magazinevoce" in host:
        return "Magazine Luiza"
    if "amazon" in host:
        return "Amazon"
    if "casasbahia" in host:
        return "Casas Bahia"
    return ""


def modelo_simples(nome: str) -> str:
    """Nome curto usado nos filtros de coleta (até o armazenamento)."""
    if not nome:
        return nome
    normalizado = re.sub(r"\s+", " ", nome)
    m = re.search(r"(.{3,}?\b\d{2,4}\s*GB\b)", normalizado, flags=re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return normalizado.split(",")[0].split(" - ")[0].strip()
