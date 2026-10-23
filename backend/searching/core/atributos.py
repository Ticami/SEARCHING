import re
from dataclasses import dataclass

# Sufixos que distinguem variantes do mesmo modelo (um S25 não pode virar S25 Ultra).
EXTRAS_CONHECIDOS = ("5G", "FE", "ULTRA", "EDGE", "PLUS", "PRO", "MAX", "LITE")

_ARMAZENAMENTO_RE = re.compile(r"\b(\d{1,4})\s*(GB|TB)\b", re.IGNORECASE)


@dataclass(frozen=True)
class Atributos:
    marca: str
    modelo: str
    armazenamento: str
    extras: tuple[str, ...]

    @property
    def extras_texto(self) -> str:
        return ",".join(self.extras)


def extrair_atributos(nome: str) -> Atributos:
    """Deriva marca, modelo, armazenamento e extras do nome comercial cadastrado."""
    texto = re.sub(r"\s+", " ", (nome or "").strip())

    armazenamento = ""
    m = _ARMAZENAMENTO_RE.search(texto)
    if m:
        armazenamento = f"{m.group(1)}{m.group(2).upper()}"
        texto = (texto[: m.start()] + texto[m.end():]).strip()

    partes = texto.split(" ")
    marca = partes[0] if partes and partes[0] else ""
    restante = partes[1:]

    extras: list[str] = []
    modelo_tokens: list[str] = []
    for tok in restante:
        base = tok.upper()
        if base.endswith("+"):
            # "S24+" -> modelo "S24" com extra "+"
            extras.append("+")
            base = base[:-1]
            tok = tok[:-1]
        if base in EXTRAS_CONHECIDOS:
            extras.append(base)
        elif tok:
            modelo_tokens.append(tok)

    return Atributos(
        marca=marca,
        modelo=" ".join(modelo_tokens),
        armazenamento=armazenamento,
        extras=tuple(sorted(set(extras))),
    )
