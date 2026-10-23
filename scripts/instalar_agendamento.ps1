<#
.SYNOPSIS
  Cria ou atualiza a tarefa do Agendador de Tarefas do Windows que roda a coleta do SEARCHING.

.DESCRIPTION
  A tarefa executa "python -m searching.run --origem agendada" dentro de backend\, sem depender do
  servidor web aberto. Se o computador estiver desligado ou dormindo no horario, a tarefa roda
  assim que possivel depois (StartWhenAvailable). Com -AcordarPC, ela tambem acorda o computador.

  A tarefa roda com o seu usuario, quando voce estiver logado (o Chrome abre visivel). Os filtros de
  loja e modelo do modo automatico ficam em backend\config.json.

.EXAMPLE
  .\instalar_agendamento.ps1                       # todos os dias as 12:00
  .\instalar_agendamento.ps1 -Horas 09:00,18:30 -Dias Mon,Tue,Wed,Thu,Fri
  .\instalar_agendamento.ps1 -AcordarPC            # acorda o computador no horario
  .\instalar_agendamento.ps1 -Desativar            # mantem a tarefa, mas desligada
  .\instalar_agendamento.ps1 -Remover              # apaga a tarefa
  .\instalar_agendamento.ps1 -SomenteMostrar       # mostra o que seria criado, sem criar
#>
[CmdletBinding()]
param(
    [string[]]$Horas = @("12:00"),
    [string[]]$Dias = @("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"),
    [string]$Nome = "SEARCHING - Coleta",
    [switch]$AcordarPC,
    [switch]$Desativar,
    [switch]$Remover,
    [switch]$SomenteMostrar
)

$ErrorActionPreference = "Stop"

$raiz = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $raiz "backend"
$python = Join-Path $backend "venv\Scripts\python.exe"

if ($Remover) {
    Unregister-ScheduledTask -TaskName $Nome -Confirm:$false
    Write-Host "Tarefa '$Nome' removida."
    return
}

if ($Desativar) {
    Disable-ScheduledTask -TaskName $Nome | Out-Null
    Write-Host "Tarefa '$Nome' desativada."
    return
}

# --- validacao dos parametros ---
$horasValidas = @()
foreach ($h in ($Horas | ForEach-Object { $_ -split "," } | ForEach-Object { $_.Trim() } | Where-Object { $_ })) {
    if ($h -notmatch '^([01]?\d|2[0-3]):[0-5]\d$') { throw "Horario invalido: '$h'. Use HH:mm (ex.: 12:00)." }
    $horasValidas += $h
}
if ($horasValidas.Count -eq 0) { throw "Informe pelo menos um horario." }

$mapaDias = @{ mon = "Monday"; tue = "Tuesday"; wed = "Wednesday"; thu = "Thursday"; fri = "Friday"; sat = "Saturday"; sun = "Sunday" }
$diasValidos = @()
foreach ($d in ($Dias | ForEach-Object { $_ -split "," } | ForEach-Object { $_.Trim().ToLower() } | Where-Object { $_ })) {
    $chave = $d.Substring(0, [Math]::Min(3, $d.Length))
    if (-not $mapaDias.ContainsKey($chave)) { throw "Dia invalido: '$d'. Use Mon,Tue,Wed,Thu,Fri,Sat,Sun." }
    if ($diasValidos -notcontains $mapaDias[$chave]) { $diasValidos += $mapaDias[$chave] }
}
if ($diasValidos.Count -eq 0) { throw "Informe pelo menos um dia da semana." }

if (-not (Test-Path $python)) {
    throw "Ambiente virtual nao encontrado em '$python'. Rode iniciar_searching.bat uma vez para cria-lo."
}

# --- definicao da tarefa ---
$gatilhos = foreach ($h in $horasValidas) {
    if ($diasValidos.Count -eq 7) {
        New-ScheduledTaskTrigger -Daily -At $h
    }
    else {
        New-ScheduledTaskTrigger -Weekly -DaysOfWeek $diasValidos -At $h
    }
}

$acao = New-ScheduledTaskAction -Execute $python -Argument "-m searching.run --origem agendada" -WorkingDirectory $backend

$parametrosConfig = @{
    StartWhenAvailable         = $true   # roda assim que possivel apos uma execucao perdida
    AllowStartIfOnBatteries    = $true
    DontStopIfGoingOnBatteries = $true
    MultipleInstances          = "IgnoreNew"
    ExecutionTimeLimit         = (New-TimeSpan -Hours 2)
}
if ($AcordarPC) { $parametrosConfig["WakeToRun"] = $true }
$config = New-ScheduledTaskSettingsSet @parametrosConfig

$usuario = "$env:USERDOMAIN\$env:USERNAME"
$principal = New-ScheduledTaskPrincipal -UserId $usuario -LogonType Interactive -RunLevel Limited

if ($SomenteMostrar) {
    Write-Host "Tarefa: $Nome"
    Write-Host "Comando: $python -m searching.run --origem agendada  (pasta: $backend)"
    Write-Host "Horarios: $($horasValidas -join ', ')"
    Write-Host "Dias: $($diasValidos -join ', ')"
    Write-Host "Acordar o PC: $([bool]$AcordarPC)"
    Write-Host "Usuario: $usuario (somente com a sessao aberta)"
    Write-Host "(nada foi criado: -SomenteMostrar)"
    return
}

Register-ScheduledTask -TaskName $Nome -Action $acao -Trigger $gatilhos -Settings $config -Principal $principal `
    -Description "Coleta de precos do SEARCHING" -Force | Out-Null
Enable-ScheduledTask -TaskName $Nome | Out-Null

$info = Get-ScheduledTaskInfo -TaskName $Nome
Write-Host "Tarefa '$Nome' criada: $($horasValidas -join ', ') ($($diasValidos.Count) dia(s) por semana)."
Write-Host "Proxima execucao: $($info.NextRunTime)"
