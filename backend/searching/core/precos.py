import re

# Aceita "R$ 1.299,00", "R$ 3.167 , 12" (formato legado com espaços) e "1299,00".
_PRECO_RE = re.compile(r"(?:R\$\s*)?(\d{1,3}(?:\.\d{3})*|\d+)\s*,\s*(\d{2})(?!\d)")


def parse_preco_centavos(texto) -> int | None:
    """Converte o texto de um preço em centavos inteiros; None se não houver preço."""
    if texto is None:
        return None
    m = _PRECO_RE.search(str(texto))
    if not m:
        return None
    inteiro = m.group(1).replace(".", "")
    return int(inteiro) * 100 + int(m.group(2))


def formatar_brl(centavos: int | None) -> str:
    if centavos is None:
        return "N/A"
    reais, cent = divmod(centavos, 100)
    return f"R$ {reais:,}".replace(",", ".") + f",{cent:02d}"
