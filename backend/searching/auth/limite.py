"""Limite de requisições por janela deslizante (em memória, por processo).

Chave = usuário logado (ou IP, quando não há login). Com vários processos do gunicorn o limite efetivo é por processo;
é uma proteção contra abuso/automação descontrolada, não um contador exato. Limites por minuto, configuráveis por ambiente:
SEARCHING_LIMITE_REQ_MIN (leitura, 600), SEARCHING_LIMITE_ESCRITA_MIN (escritas, 120), SEARCHING_LIMITE_EXPORTAR_MIN (Excel, 10).
Valor 0 desliga aquele limite.
"""
import os
import threading
import time
from collections import deque


class Limitador:
    def __init__(self, relogio=time.monotonic):
        self._relogio = relogio
        self._eventos: dict[tuple, deque] = {}
        self._trava = threading.Lock()
        self._ultima_limpeza = relogio()

    def permitir(self, chave: tuple, maximo: int, janela_s: float = 60.0) -> float | None:
        """Registra a requisição. Devolve None se passou ou os segundos até poder tentar de novo."""
        if maximo <= 0:
            return None
        agora = self._relogio()
        with self._trava:
            fila = self._eventos.setdefault(chave, deque())
            while fila and agora - fila[0] >= janela_s:
                fila.popleft()
            if len(fila) >= maximo:
                return max(0.1, janela_s - (agora - fila[0]))
            fila.append(agora)
            if agora - self._ultima_limpeza > 300:  # solta chaves paradas
                for k in [k for k, f in self._eventos.items() if not f or agora - f[-1] >= janela_s]:
                    del self._eventos[k]
                self._ultima_limpeza = agora
        return None


def _numero(nome: str, padrao: int) -> int:
    try:
        return int(os.environ.get(nome, padrao))
    except ValueError:
        return padrao


def limites() -> dict[str, int]:
    return {
        "leitura": _numero("SEARCHING_LIMITE_REQ_MIN", 600),
        "escrita": _numero("SEARCHING_LIMITE_ESCRITA_MIN", 120),
        "exportar": _numero("SEARCHING_LIMITE_EXPORTAR_MIN", 10),
    }
