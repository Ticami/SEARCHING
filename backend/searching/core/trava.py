"""Trava de execução simultânea (RF-11): um arquivo com o PID do processo que está coletando."""
import os
import sys
import time
from pathlib import Path

from ..db.session import BACKEND_DIR

TRAVA_PADRAO = BACKEND_DIR / "data" / "coleta.lock"
# Trava mais antiga que isso é considerada abandonada, mesmo que o PID exista.
IDADE_MAXIMA_S = 3 * 3600


class ColetaEmAndamento(RuntimeError):
    pass


def _pid_vivo(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        k32 = ctypes.windll.kernel32
        handle = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        try:
            codigo = ctypes.c_ulong()
            return bool(k32.GetExitCodeProcess(handle, ctypes.byref(codigo))) and codigo.value == STILL_ACTIVE
        finally:
            k32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _trava_abandonada(caminho: Path) -> bool:
    try:
        pid = int(caminho.read_text().strip() or 0)
        idade = time.time() - caminho.stat().st_mtime
    except (OSError, ValueError):
        return True
    return idade > IDADE_MAXIMA_S or not _pid_vivo(pid)


class TravaColeta:
    def __init__(self, caminho: Path | None = None):
        self.caminho = Path(caminho or TRAVA_PADRAO)

    def __enter__(self):
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(2):
            try:
                fd = os.open(self.caminho, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                if _trava_abandonada(self.caminho):
                    self.caminho.unlink(missing_ok=True)
                    continue
                raise ColetaEmAndamento("Já existe uma coleta em andamento.") from None
            with os.fdopen(fd, "w") as f:
                f.write(str(os.getpid()))
            return self
        raise ColetaEmAndamento("Não foi possível obter a trava de coleta.")

    def __exit__(self, *exc):
        self.caminho.unlink(missing_ok=True)
        return False
