# Scheduled-task wrapper: checks LinkedIn/Indeed/Glassdoor email alerts only.
# Registered as the "JobAggregator-EmailCheck" Windows Task Scheduler task
# (every 10 minutes). Skips Workday/API sources — see run_full_aggregate.ps1
# for those, run on a separate twice-daily schedule.
#
# Uses Start-Process with file redirection (not a `2>&1 | Add-Content`
# pipe) — PowerShell 5.1 wraps a native process's stderr lines as
# ErrorRecords when piped that way, which combined with an aggressive
# ErrorActionPreference kills the script on Python's very first log line
# (logging module writes INFO to stderr by default).

$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
$logFile = Join-Path $projectRoot "logs\email_check.log"
New-Item -ItemType Directory -Force -Path (Split-Path $logFile) | Out-Null

$stdoutTmp = Join-Path $env:TEMP "job-aggregator-email-stdout.log"
$stderrTmp = Join-Path $env:TEMP "job-aggregator-email-stderr.log"

$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
"[$timestamp] Starting email check" | Add-Content $logFile

$proc = Start-Process -FilePath $venvPython `
    -ArgumentList "scripts/aggregate.py", "--skip-workday", "--skip-apis" `
    -WorkingDirectory $projectRoot `
    -RedirectStandardOutput $stdoutTmp `
    -RedirectStandardError $stderrTmp `
    -NoNewWindow -Wait -PassThru

Get-Content $stdoutTmp -ErrorAction SilentlyContinue | Add-Content $logFile
Get-Content $stderrTmp -ErrorAction SilentlyContinue | Add-Content $logFile
Remove-Item $stdoutTmp, $stderrTmp -ErrorAction SilentlyContinue

$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
"[$timestamp] Done (exit code $($proc.ExitCode))" | Add-Content $logFile
