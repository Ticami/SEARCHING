"""Proteções de um servidor de uso local: só loopback, CORS restrito e checagem de Host/Origin (RF-34)."""
import os
from dataclasses import dataclass

HOSTS_LOOPBACK = ("127.0.0.1", "localhost", "::1")
PORTA_PADRAO = 5000
PORTA_FRONTEND = 5173  # Vite (npm run dev)
_METODOS_SEGUROS = ("GET", "HEAD", "OPTIONS")


@dataclass(frozen=True)
class ConfigServidor:
    host: str
    porta: int
    debug: bool
    aviso: str | None = None


def configuracao_servidor(env: dict | None = None) -> ConfigServidor:
    """Host, porta e debug do servidor. Nunca escuta fora do próprio computador, mesmo se pedirem."""
    env = os.environ if env is None else env
    aviso = None
    host = (env.get("SEARCHING_HOST") or "127.0.0.1").strip()
    if host not in HOSTS_LOOPBACK:
        aviso = f"SEARCHING_HOST={host!r} ignorado: o servidor só escuta em 127.0.0.1 (uso local)."
        host = "127.0.0.1"
    try:
        porta = int(env.get("SEARCHING_PORT") or PORTA_PADRAO)
    except ValueError:
        porta = PORTA_PADRAO
    debug = (env.get("SEARCHING_DEBUG") or "0").strip().lower() in ("1", "true", "sim")
    return ConfigServidor(host, porta, debug, aviso)


def origens_permitidas(env: dict | None = None, porta: int = PORTA_PADRAO) -> frozenset[str]:
    """Endereços de onde o navegador pode chamar a API: o frontend (Vite) e o próprio servidor."""
    env = os.environ if env is None else env
    origens = {
        f"http://{h}:{p}" for h in ("localhost", "127.0.0.1") for p in (PORTA_FRONTEND, porta)
    }
    for extra in (env.get("SEARCHING_ORIGENS") or "").split(","):
        extra = extra.strip().rstrip("/")
        if extra.startswith(("http://localhost", "http://127.0.0.1")):  # só endereços locais
            origens.add(extra)
    return frozenset(origens)


def host_permitido(cabecalho_host: str | None) -> bool:
    """Evita DNS rebinding: o cabeçalho Host precisa ser um endereço local."""
    if not cabecalho_host:
        return False
    host = cabecalho_host.strip().lower()
    if host.startswith("["):  # [::1]:5000
        host = host[1:].split("]")[0]
    else:
        host = host.rsplit(":", 1)[0] if host.count(":") == 1 else host
    return host in HOSTS_LOOPBACK


def requisicao_bloqueada(metodo: str, cabecalho_host: str | None, origem: str | None, permitidas: frozenset[str]) -> str | None:
    """Motivo do bloqueio, ou None se a requisição pode seguir.

    Qualquer site aberto no navegador consegue enviar um POST para 127.0.0.1; o navegador sempre manda o
    Origin nesses casos, então recusamos escritas cujo Origin não seja um dos nossos (proteção contra CSRF).
    """
    if not host_permitido(cabecalho_host):
        return "Host não permitido"
    if metodo.upper() not in _METODOS_SEGUROS and origem and origem.rstrip("/") not in permitidas:
        return "Origem não permitida"
    return None
