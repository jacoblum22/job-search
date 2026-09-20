# Scheduled-task wrapper: runs every source (Workday + Adzuna/CareerJet +
# email alerts). Registered as "JobAggregator-FullRun-AM" / "-PM" in Windows
# Task Scheduler, twice a day. See run_email_check.ps1 for the more frequent
# email-only check.
#
# Uses Start-Process with file redirection (not a `2>&1 | Add-Content`
# pipe) — PowerShell 5.1 wraps a native process's stderr lines as
# ErrorRecords when piped that way, which combined with an aggressive
# ErrorActionPreference kills the script on Python's very first log line
# (logging module writes INFO to stderr by default).

$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
$logFile = Join-Path $projectRoot "logs\full_aggregate.log"
New-Item -ItemType Directory -Force -Path (Split-Path $logFile) | Out-Null

$stdoutTmp = Join-Path $env:TEMP "job-aggregator-full-stdout.log"
$stderrTmp = Join-Path $env:TEMP "job-aggregator-full-stderr.log"

$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
"[$timestamp] Starting full aggregation" | Add-Content $logFile

$proc = Start-Process -FilePath $venvPython `
    -ArgumentList "scripts/aggregate.py" `
    -WorkingDirectory $projectRoot `
    -RedirectStandardOutput $stdoutTmp `
    -RedirectStandardError $stderrTmp `
    -NoNewWindow -Wait -PassThru

Get-Content $stdoutTmp -ErrorAction SilentlyContinue | Add-Content $logFile
Get-Content $stderrTmp -ErrorAction SilentlyContinue | Add-Content $logFile
Remove-Item $stdoutTmp, $stderrTmp -ErrorAction SilentlyContinue

$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
"[$timestamp] Done (exit code $($proc.ExitCode))" | Add-Content $logFile
