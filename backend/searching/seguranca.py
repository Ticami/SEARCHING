"""Proteções de um servidor de uso local: só loopback, CORS restrito e checagem de Host/Origin (RF-34)."""
import os
from dataclasses import dataclass
from urllib.parse import urlparse

from . import modo as _modo

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
    if _modo.hospedado(env):
        # Hospedado: o servidor fica atrás de um proxy HTTPS (ou do gunicorn em container); quem restringe é o Host/Origin.
        host = (env.get("SEARCHING_HOST") or "127.0.0.1").strip()
        try:
            porta = int(env.get("SEARCHING_PORT") or PORTA_PADRAO)
        except ValueError:
            porta = PORTA_PADRAO
        return ConfigServidor(host, porta, False, None)
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
    if _modo.hospedado(env):
        origens = {_modo.url_publica(env)}
        for extra in (env.get("SEARCHING_ORIGENS") or "").split(","):
            extra = extra.strip().rstrip("/")
            if extra.startswith("https://"):
                origens.add(extra)
        return frozenset(origens)
    origens = {
        f"http://{h}:{p}" for h in ("localhost", "127.0.0.1") for p in (PORTA_FRONTEND, porta)
    }
    for extra in (env.get("SEARCHING_ORIGENS") or "").split(","):
        extra = extra.strip().rstrip("/")
        if extra.startswith(("http://localhost", "http://127.0.0.1")):  # só endereços locais
            origens.add(extra)
    return frozenset(origens)


def ids_extensao_permitidos(env: dict | None = None) -> frozenset[str]:
    """SEARCHING_EXTENSAO_IDS: ids oficiais da extensão (Chrome e Edge têm ids diferentes), separados por vírgula."""
    env = os.environ if env is None else env
    return frozenset(i.strip() for i in (env.get("SEARCHING_EXTENSAO_IDS") or "").split(",") if i.strip())


def extensao_autorizada(origem: str | None, env: dict | None = None) -> bool:
    """Sem lista configurada, vale só o token. Com lista, a chamada da extensão precisa vir de chrome-extension://<id da lista>."""
    ids = ids_extensao_permitidos(env)
    if not ids:
        return True
    prefixo = "chrome-extension://"
    return bool(origem) and origem.startswith(prefixo) and origem[len(prefixo):].rstrip("/") in ids


def _versao(texto: str | None) -> tuple[int, ...]:
    try:
        return tuple(int(p) for p in (texto or "").strip().split("."))
    except ValueError:
        return ()


def versao_da_extensao_ok(enviada: str | None, env: dict | None = None) -> tuple[bool, str]:
    """SEARCHING_EXTENSAO_VERSAO_MINIMA (ex.: 2.1.0) força a atualização da extensão. Sem ela, qualquer versão vale.
    Devolve (ok, versão mínima)."""
    env = os.environ if env is None else env
    minima = (env.get("SEARCHING_EXTENSAO_VERSAO_MINIMA") or "").strip()
    if not minima:
        return True, ""
    return _versao(enviada) >= _versao(minima) and bool(_versao(enviada)), minima


def host_permitido(cabecalho_host: str | None, env: dict | None = None) -> bool:
    """Evita DNS rebinding: o cabeçalho Host precisa ser um endereço local (ou, hospedado, o domínio público)."""
    if not cabecalho_host:
        return False
    host = cabecalho_host.strip().lower()
    env = os.environ if env is None else env
    if _modo.hospedado(env):
        return host.split(":")[0] == urlparse(_modo.url_publica(env)).hostname
    if host.startswith("["):  # [::1]:5000
        host = host[1:].split("]")[0]
    else:
        host = host.rsplit(":", 1)[0] if host.count(":") == 1 else host
    return host in HOSTS_LOOPBACK


def requisicao_bloqueada(
    metodo: str, cabecalho_host: str | None, origem: str | None, permitidas: frozenset[str], env: dict | None = None,
) -> str | None:
    """Motivo do bloqueio, ou None se a requisição pode seguir.

    Qualquer site aberto no navegador consegue enviar um POST para 127.0.0.1; o navegador sempre manda o
    Origin nesses casos, então recusamos escritas cujo Origin não seja um dos nossos (proteção contra CSRF).
    """
    if not host_permitido(cabecalho_host, env):
        return "Host não permitido"
    if metodo.upper() not in _METODOS_SEGUROS and origem and origem.rstrip("/") not in permitidas:
        return "Origem não permitida"
    return None
