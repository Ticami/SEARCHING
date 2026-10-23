"""Ponte entre a interface e o Agendador de Tarefas do Windows (a tarefa em si é criada por scripts/instalar_agendamento.ps1)."""
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .db.models import Execucao
from .db.session import BACKEND_DIR

NOME_TAREFA = "SEARCHING - Coleta"
SCRIPT = BACKEND_DIR.parent / "scripts" / "instalar_agendamento.ps1"
CONFIG_PATH = BACKEND_DIR / "config.json"

TODOS_OS_DIAS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
_DIAS_PT = {"seg": "mon", "ter": "tue", "qua": "wed", "qui": "thu", "sex": "fri", "sab": "sat", "dom": "sun"}
_HORA_RE = re.compile(r"([01]\d|2[0-3]):[0-5]\d")


def horario_valido(texto) -> bool:
    return bool(_HORA_RE.fullmatch(str(texto).strip()))


def normalizar_dias(dias) -> list[str]:
    normais = [_DIAS_PT.get(str(d).lower().strip(), str(d).lower().strip()) for d in (dias or [])]
    return [d for d in TODOS_OS_DIAS if d in normais]


def config_padrao() -> dict:
    # Padrão do PRD: todos os dias às 12:00.
    return {"enabled": False, "times": ["12:00"], "days": list(TODOS_OS_DIAS), "stores": [], "include": [], "exclude": []}


def carregar_config(caminho: Path = CONFIG_PATH) -> dict:
    cfg = config_padrao()
    try:
        cfg.update(json.loads(Path(caminho).read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass
    return cfg


def salvar_config(cfg: dict, caminho: Path = CONFIG_PATH) -> None:
    Path(caminho).write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def filtros_da_agenda(caminho: Path = CONFIG_PATH) -> tuple[list, list, list]:
    """Lojas, modelos incluídos e excluídos que a coleta agendada deve usar."""
    cfg = carregar_config(caminho)
    return cfg.get("stores") or [], cfg.get("include") or [], cfg.get("exclude") or []


def comando_instalacao(horas: list[str], dias: list[str]) -> str:
    """Comando para o usuário rodar à mão caso a interface não consiga criar a tarefa."""
    return (
        f'powershell -ExecutionPolicy Bypass -File "{SCRIPT}" '
        f'-Horas {",".join(horas)} -Dias {",".join(d.capitalize() for d in dias)}'
    )


def _powershell(argumentos: list[str], timeout: int = 60) -> subprocess.CompletedProcess:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", *argumentos],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, creationflags=flags,
    )


_CONSULTA_PS = """
$t = Get-ScheduledTask -TaskName '__NOME__' -ErrorAction SilentlyContinue
if (-not $t) { '{"instalada":false}'; return }
$i = $t | Get-ScheduledTaskInfo
function Iso($d) { if ($d -and $d.Year -gt 2000) { $d.ToString('s') } else { $null } }
[pscustomobject]@{
  instalada = $true
  ativa = ($t.State -ne 'Disabled')
  estado = [string]$t.State
  proxima_execucao = (Iso $i.NextRunTime)
  ultima_execucao_windows = (Iso $i.LastRunTime)
  resultado_windows = $i.LastTaskResult
  horarios = @($t.Triggers | ForEach-Object { ([datetime]$_.StartBoundary).ToString('HH:mm') })
} | ConvertTo-Json -Compress
"""


def consultar_tarefa() -> dict:
    """Estado da tarefa no Windows: instalada, ativa e próxima execução."""
    if sys.platform != "win32":
        return {"suportado": False, "instalada": False}
    try:
        proc = _powershell(["-Command", _CONSULTA_PS.replace("__NOME__", NOME_TAREFA)])
        dados = json.loads(proc.stdout.strip().splitlines()[-1])
    except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
        return {"suportado": True, "instalada": False, "erro": "não foi possível consultar o Agendador de Tarefas"}
    dados["suportado"] = True
    return dados


def aplicar(cfg: dict) -> tuple[bool, str]:
    """Cria/atualiza (ou desativa) a tarefa do Windows conforme a configuração. Devolve (ok, mensagem)."""
    if sys.platform != "win32":
        return False, "O agendamento automático só está disponível no Windows."

    horas = sorted({str(t).strip() for t in cfg.get("times", []) if horario_valido(t)})
    dias = normalizar_dias(cfg.get("days")) or list(TODOS_OS_DIAS)

    if not cfg.get("enabled"):
        if not consultar_tarefa().get("instalada"):
            return True, "Agendamento salvo (desativado)."
        proc = _powershell(["-File", str(SCRIPT), "-Nome", NOME_TAREFA, "-Desativar"])
        return proc.returncode == 0, "Agendamento desativado." if proc.returncode == 0 else _erro(proc)

    if not horas:
        return False, "Informe pelo menos um horário para ativar o agendamento."

    proc = _powershell(["-File", str(SCRIPT), "-Nome", NOME_TAREFA, "-Horas", ",".join(horas), "-Dias", ",".join(dias)])
    if proc.returncode != 0:
        return False, f"{_erro(proc)} Para criar manualmente: {comando_instalacao(horas, dias)}"
    return True, "Agendamento salvo e tarefa do Windows atualizada."


def _erro(proc: subprocess.CompletedProcess) -> str:
    texto = (proc.stderr or proc.stdout or "erro desconhecido").strip().splitlines()
    return texto[0] if texto else "erro desconhecido"


def ultima_execucao(s: Session) -> dict | None:
    e = s.scalars(select(Execucao).order_by(Execucao.iniciada_em.desc()).limit(1)).first()
    if e is None:
        return None
    duracao = (e.finalizada_em - e.iniciada_em).total_seconds() if e.finalizada_em else None
    return {
        "id": e.id,
        "iniciada_em": e.iniciada_em.isoformat(timespec="seconds"),
        "duracao_s": round(duracao) if duracao is not None else None,
        "origem": e.origem,
        "total": e.total,
        "ok": e.ok,
        "falhas": e.falhas,
        "links_corrigidos": e.links_corrigidos,
        "em_revisao": e.em_revisao,
        "em_andamento": e.finalizada_em is None,
    }
