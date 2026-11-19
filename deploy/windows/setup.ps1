#Requires -Version 5.1
<#
.SYNOPSIS
  Prepara o QUANT HERMES numa máquina Windows, ao lado do terminal RoboForex.

  Cria o venv, instala dependências (incluindo MetaTrader5 neste SO),
  copia .env se faltar, bloqueia a porta 8000 vinda de fora e registra
  tarefas: subir no logon do mesmo usuário do terminal, backup e rotação de log.

  Não abre o terminal e não envia ordem.
#>
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $Root

function Find-PythonLauncher {
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        return @{ Exe = $py.Source; Prefix = @("-3.11") }
    }
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        return @{ Exe = $python.Source; Prefix = @() }
    }
    throw "Python 3.11 não encontrado. Instale o python.org de 64 bits e marque 'Add to PATH'."
}

$launcher = Find-PythonLauncher
$venvPython = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    & $launcher.Exe @($launcher.Prefix + @("-m", "venv", ".venv"))
    if ($LASTEXITCODE -ne 0) { throw "Falha ao criar o venv." }
}

& $venvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "Falha ao atualizar o pip." }
& $venvPython -m pip install -e ".[dev]"
if ($LASTEXITCODE -ne 0) { throw "Falha ao instalar as dependências." }

$envExample = Join-Path $Root ".env.production.example"
$envFile = Join-Path $Root ".env"
if (-not (Test-Path $envFile)) {
    Copy-Item $envExample $envFile
    Write-Warning "Criei .env a partir do exemplo. Preencha HERMES_OPERATOR_TOKEN antes de subir."
}

New-Item -ItemType Directory -Force -Path (Join-Path $Root "logs") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $Root "data\storage") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $Root "data\backups") | Out-Null

try {
    $ruleName = "QUANT-HERMES-Block-8000-External"
    $existing = Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
    if (-not $existing) {
        New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Action Block -Protocol TCP -LocalPort 8000 -RemoteAddress Internet,Intranet -Profile Any | Out-Null
    }
    Write-Host "Firewall: entrada externa na porta 8000 bloqueada. O processo escuta em 127.0.0.1."
} catch {
    Write-Warning "Sem permissão de firewall. A API continua presa a 127.0.0.1 pelo próprio processo."
}

$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero)
$user = $env:USERNAME

function Register-HermesTask {
    param($Name, $Arguments, $Trigger)
    $action = New-ScheduledTaskAction -Execute $venvPython -Argument $Arguments -WorkingDirectory $Root
    Register-ScheduledTask -TaskName $Name -Action $action -Trigger $Trigger -Settings $settings -User $user -Force | Out-Null
    Write-Host "Tarefa registrada: $Name"
}

# AtLogOn do mesmo usuário que abre o terminal. Serviço de sessão 0 não enxerga o MT5.
try {
    $logon = New-ScheduledTaskTrigger -AtLogOn -User $user
    Register-HermesTask -Name "QUANT-HERMES" -Arguments "deploy\windows\service_main.py" -Trigger $logon

    $backup = New-ScheduledTaskTrigger -Daily -At 3:00am
    Register-HermesTask -Name "QUANT-HERMES-Backup" -Arguments "deploy\backup_state.py" -Trigger $backup

    $rotate = New-ScheduledTaskTrigger -Daily -At 3:15am
    Register-HermesTask -Name "QUANT-HERMES-LogRotate" -Arguments "deploy\log_rotate.py" -Trigger $rotate
} catch {
    Write-Warning "Nao registrei as tarefas automaticamente: $($_.Exception.Message)"
    Write-Warning "Rode este script na sessao do mesmo usuario que abre o terminal RoboForex."
}

Write-Host "Pronto. Edite .env, abra o terminal RoboForex na conta demo e rode:"
Write-Host "  .\.venv\Scripts\python.exe deploy\preflight_check.py --require-terminal"
