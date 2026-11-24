# Install a per-user interactive scheduled task. No dependency on uv or pip.
param(
    [ValidateSet('DEBUG','INFO','WARNING','ERROR','CRITICAL')]
    [string]$LogLevel
)
$ErrorActionPreference = 'Stop'
$taskName = 'VN FaceKeys'
$projectDir = $PSScriptRoot
$python = Join-Path $projectDir '.venv\Scripts\python.exe'
$pythonw = Join-Path $projectDir '.venv\Scripts\pythonw.exe'
$entry = Join-Path $projectDir 'facekeys_bg.pyw'
$server = Join-Path $projectDir 'facekeys_server.py'
$config = Join-Path $projectDir 'config.json'
foreach ($path in @($python, $pythonw, $entry, $server, $config)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Required file not found: $path. Follow README.md and run the foreground server once."
    }
}
& $python -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)'
if ($LASTEXITCODE -ne 0) { throw 'Python 3.10 or later is required.' }
& $python $server --check
if ($LASTEXITCODE -ne 0) { throw 'Configuration check failed; fix config.json first.' }
if (Get-ScheduledTask -TaskPath '\' -TaskName 'FaceKeysVN' -ErrorAction SilentlyContinue) {
    throw 'Legacy FaceKeysVN task exists. Remove it using the upgrade steps in README.md first.'
}
$userName = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$arguments = '"' + $entry + '"'
if ($LogLevel) { $arguments += ' --loglevel ' + $LogLevel }
$action = New-ScheduledTaskAction -Execute $pythonw -Argument $arguments -WorkingDirectory $projectDir
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $userName
$principal = New-ScheduledTaskPrincipal -UserId $userName -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -MultipleInstances IgnoreNew `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1)
$existing = Get-ScheduledTask -TaskPath '\' -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing) {
    Stop-ScheduledTask -TaskPath '\' -TaskName $taskName -ErrorAction SilentlyContinue
    for ($i = 0; $i -lt 20; $i++) {
        if ((Get-ScheduledTask -TaskPath '\' -TaskName $taskName).State -ne 'Running') { break }
        Start-Sleep -Milliseconds 250
    }
    if ((Get-ScheduledTask -TaskPath '\' -TaskName $taskName).State -eq 'Running') {
        throw 'Existing task is still running. Stop it before reinstalling.'
    }
}
Register-ScheduledTask -TaskPath '\' -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description 'VN FaceKeys: facial gestures to Windows input' -Force | Out-Null
Start-ScheduledTask -TaskPath '\' -TaskName $taskName
Write-Host "Registered task '$taskName' and requested startup for $userName."
Write-Host 'Verify /health and the log before using it.'
Write-Host "Log: $(Join-Path $projectDir 'logs\facekeys.log')"
