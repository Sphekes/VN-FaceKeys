# Registers FaceKeysVN in the current interactive Windows logon session.
# Run this script from an ordinary PowerShell window, not as SYSTEM.
$ErrorActionPreference = 'Stop'
$taskName = 'FaceKeysVN'
$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonw = Join-Path $projectDir '.venv\Scripts\pythonw.exe'
$entry = Join-Path $projectDir 'facekeys_bg.pyw'

if (-not (Test-Path -LiteralPath $pythonw)) {
    throw "Python environment not found: $pythonw`nRun: uv venv --python 3.12"
}
if (-not (Test-Path -LiteralPath $entry)) {
    throw "Launcher not found: $entry"
}

$userName = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$action = New-ScheduledTaskAction -Execute $pythonw -Argument ('"' + $entry + '"') -WorkingDirectory $projectDir
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $userName
$principal = New-ScheduledTaskPrincipal -UserId $userName -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -MultipleInstances IgnoreNew `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1)

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description 'FaceKeys VN: face gestures to Windows input in interactive session' -Force | Out-Null
Start-ScheduledTask -TaskName $taskName
Write-Host "Registered and started task $taskName for $userName"
Write-Host "Log: $(Join-Path $projectDir 'logs\facekeys.log')"
Write-Host "Stop: Stop-ScheduledTask -TaskName '$taskName'"
Write-Host "Start: Start-ScheduledTask -TaskName '$taskName'"
