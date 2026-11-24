# Unregister only this project's scheduled task. Keep user data and Python.
$ErrorActionPreference = 'Stop'
$taskName = 'VN FaceKeys'
$task = Get-ScheduledTask -TaskPath '\' -TaskName $taskName -ErrorAction SilentlyContinue
if ($task) {
    Stop-ScheduledTask -TaskPath '\' -TaskName $taskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskPath '\' -TaskName $taskName -Confirm:$false
    Write-Host "Removed scheduled task: $taskName"
} else {
    Write-Host "Scheduled task not found: $taskName"
}
