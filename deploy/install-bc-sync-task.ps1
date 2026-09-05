# Register the daily Business Central consistency check as a Windows scheduled task.
# Run as Administrator once per server.
#
# The task runs:  python manage.py sync_business_central
# and appends its output to logs\bc-sync.log.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File .\deploy\install-bc-sync-task.ps1
#   powershell -ExecutionPolicy Bypass -File .\deploy\install-bc-sync-task.ps1 -At 05:30
#   powershell -ExecutionPolicy Bypass -File .\deploy\install-bc-sync-task.ps1 -Remove

param(
    [string]$AppRoot = "",
    [string]$TaskName = "WorkflowBcSync",
    [string]$At = "06:00",
    [switch]$Remove
)

$ErrorActionPreference = "Stop"

if (-not $AppRoot) {
    $AppRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}

if ($Remove) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Scheduled task '$TaskName' removed."
    return
}

$venvPython = Join-Path $AppRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    throw "Virtual environment not found at $venvPython - run: poetry install"
}

$managePy = Join-Path $AppRoot "manage.py"
if (-not (Test-Path $managePy)) {
    throw "Missing $managePy"
}

$logsDir = Join-Path $AppRoot "logs"
if (-not (Test-Path $logsDir)) {
    New-Item -ItemType Directory -Path $logsDir | Out-Null
}
$logFile = Join-Path $logsDir "bc-sync.log"

$command = "& '$venvPython' '$managePy' sync_business_central *>> '$logFile'"
$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -Command `"$command`"" `
    -WorkingDirectory $AppRoot
$trigger = New-ScheduledTaskTrigger -Daily -At $At
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Allinea i dati delle commesse con Business Central (controllo giornaliero)." `
    -User "SYSTEM" `
    -RunLevel Highest `
    -Force | Out-Null

Write-Host "Scheduled task '$TaskName' registered - runs daily at $At."
Write-Host "Log file: $logFile"
Write-Host "Run it now with: Start-ScheduledTask -TaskName $TaskName"
