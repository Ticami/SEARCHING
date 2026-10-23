from .base import LojaAdapter
from .magalu import MagaluAdapter

ADAPTADORES: list[LojaAdapter] = [MagaluAdapter()]


def adaptador_para(url: str) -> LojaAdapter | None:
    for adaptador in ADAPTADORES:
        if adaptador.reconhece(url):
            return adaptador
    return None
