# Scheduled-task wrapper: daily tailoring run (docs/tailoring-runbook.md).
# Registered as the "JobSearch-Tailoring" Windows Task Scheduler task.
# Claude drafts a resume and cover letter for the best new A-tier jobs and stops
# at "Ready for review" on the dashboard. It never applies, sends, commits or pushes.
#
# Before picking jobs it runs a full scrape (scripts/aggregate.py, every source) so the queue
# sees today's postings; the queue then rescores every job. The Azure job scrapes every
# morning (docs/azure-scrape-job.md), so when a full run finished in the last 6 hours the
# scrape here fetches only the sources that block Azure (settings.yaml cloud_sources), and
# does the full scrape only when that job didn't run. -NoScrape skips the scrape, and
# -JobId / -ResumeOnly runs never scrape since they don't pick new jobs. If the scrape fails
# the run still tailors from the jobs already in the database and logs why.
#
# Test on one job:   .\scripts\run_tailoring.ps1 -Limit 1   (or -JobId 812)
# Normal daily run:  .\scripts\run_tailoring.ps1            (tailor.daily_cap jobs)
# Waiting rounds only (repair or letter rounds on applications up for review, no new jobs):
#                    .\scripts\run_tailoring.ps1 -ResumeOnly
# Afterwards run_tailoring_review.ps1 reviews the log and opens a PR for any pipeline
# fixes (docs/run-review-task.md); -NoReview skips that.

param(
    [int]$JobId = 0,
    [int]$Limit = 0,
    [double]$MaxBudgetUsd = 0,
    [switch]$NoReview,
    [switch]$NoScrape,
    [switch]$ResumeOnly
)

$projectRoot = Split-Path -Parent $PSScriptRoot
$date = Get-Date -Format "yyyy-MM-dd"
$stamp = Get-Date -Format "yyyy-MM-dd_HHmm"
$logDir = Join-Path $projectRoot "logs\tailoring"
$logFile = Join-Path $projectRoot "logs\tailoring.log"
$transcript = Join-Path $logDir "$stamp.jsonl"
$digestDir = Join-Path $projectRoot "materials\tailor\digests"
New-Item -ItemType Directory -Force -Path $logDir, $digestDir | Out-Null

function Log($msg) { "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $msg" | Add-Content $logFile -Encoding UTF8 }

# PowerShell 5.1 pipes text to native programs as ASCII unless told otherwise.
$utf8 = New-Object System.Text.UTF8Encoding $false
$OutputEncoding = $utf8
[Console]::OutputEncoding = $utf8

Set-Location $projectRoot
if ($ResumeOnly) {
    $queueCmd = "uv run python -m src.tailor queue --limit 0"
    $mode = "waiting rounds only"
} elseif ($JobId -gt 0) {
    $queueCmd = "uv run python -m src.tailor queue --job-id $JobId"
    $mode = "job $JobId"
} elseif ($Limit -gt 0) {
    $queueCmd = "uv run python -m src.tailor queue --limit $Limit"
    $mode = "limit $Limit"
} else {
    $queueCmd = "uv run python -m src.tailor queue"
    $mode = "daily cap"
}
Log "Starting tailoring run ($mode); transcript $transcript"
# While this file names a live process, the dashboard shows the run and won't start another,
# even after the dashboard server restarts (src/tailor_runner.py). Removed when the run ends.
$runFile = Join-Path $projectRoot "logs\tailoring.run.json"
@{ pid = $PID; started = (Get-Date -Format "yyyy-MM-ddTHH:mm:sszzz"); limit = $Limit; mode = $mode } |
    ConvertTo-Json -Compress | Set-Content $runFile -Encoding UTF8
. (Join-Path $PSScriptRoot "uv_path.ps1")
if (-not (Add-UvToPath)) {
    Log "ERROR: uv not found on PATH or in the usual install folders; nothing ran"
    Remove-Item $runFile -ErrorAction SilentlyContinue
    exit 1
}

uv sync -q 2>&1 | Out-Null

# Fresh postings first. Start-Process with file redirection, not a pipe: PowerShell 5.1 turns
# Python's stderr log lines into errors when piped (see run_full_aggregate.ps1).
if (-not $NoScrape -and -not $ResumeOnly -and $JobId -le 0) {
    $scrapeLog = Join-Path $projectRoot "logs\full_aggregate.log"
    $stdoutTmp = Join-Path $env:TEMP "job-tailoring-scrape-stdout.log"
    $stderrTmp = Join-Path $env:TEMP "job-tailoring-scrape-stderr.log"
    "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Starting full aggregation (before tailoring)" | Add-Content $scrapeLog
    Log "Scraping every source before picking jobs (log: logs\full_aggregate.log)"
    $scrapeStart = Get-Date
    try {
        # --wait-lock: if another scrape (the Azure job, the email check) is mid-way, wait for
        # it (up to 30 min) instead of skipping the scrape; --skip-if-fresh: after a full run in
        # the last 6 hours, fetch only what the Azure job leaves here (exit 4 if that's nothing).
        $proc = Start-Process -FilePath (Join-Path $projectRoot ".venv\Scripts\python.exe") `
            -ArgumentList "scripts/aggregate.py", "--wait-lock", "1800", "--skip-if-fresh", "6" `
            -WorkingDirectory $projectRoot `
            -RedirectStandardOutput $stdoutTmp -RedirectStandardError $stderrTmp `
            -NoNewWindow -Wait -PassThru
        $code = $proc.ExitCode
    } catch {
        $code = "not started: $($_.Exception.Message)"
    }
    Get-Content $stdoutTmp, $stderrTmp -ErrorAction SilentlyContinue | Add-Content $scrapeLog
    Remove-Item $stdoutTmp, $stderrTmp -ErrorAction SilentlyContinue
    "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Done (exit code $code)" | Add-Content $scrapeLog
    $mins = ((Get-Date) - $scrapeStart).TotalMinutes
    if ($code -eq 0) {
        Log ("Scrape finished in {0:N0} min" -f $mins)
    } elseif ($code -eq 4) {
        Log "Skipped the scrape: a full run (usually the Azure job) finished in the last 6 hours"
    } elseif ($code -eq 3) {
        Log "WARNING: another scrape held the lock for 30 min; tailoring from the jobs already in jobs.db"
    } else {
        Log ("WARNING: scrape failed (exit code {0}) after {1:N0} min; tailoring from the jobs already in jobs.db" -f $code, $mins)
    }
}

# The evening Chrome task's hand-off (docs/browser-description-task.md): store the
# descriptions it left in .browser-queue\ and write a fresh queue.json for tonight. Runs
# here, not in the scrape, because the scrape may run in Azure, where this folder isn't.
$bqOut = & (Join-Path $projectRoot ".venv\Scripts\python.exe") scripts\browser_queue.py sync 2>&1 | ForEach-Object { "$_" }
if ($LASTEXITCODE -ne 0) { Log "WARNING: browser queue sync failed (exit $LASTEXITCODE)" }
$bqOut | Where-Object { $_ -notmatch "UV_NATIVE_TLS" } | ForEach-Object { Log $_ }

# The prompt is everything between the two markers in the runbook.
$doc = Get-Content (Join-Path $projectRoot "docs\tailoring-runbook.md") -Raw -Encoding UTF8
$prompt = ($doc -split "<!-- prompt start -->", 2)[1]
$prompt = ($prompt -split "<!-- prompt end -->", 2)[0]
$prompt = $prompt.Replace("{DATE}", $date).Replace("{QUEUE}", $queueCmd)

$tools = @(
    "Read", "Glob", "Grep", "WebSearch", "Agent",
    "Edit(materials/applications/**)", "Edit(materials/companies/**)",
    "Bash(uv run python -m src.tailor:*)"
)
# --strict-mcp-config with no --mcp-config: no connectors (Gmail, Calendar...) are loaded.
$claudeArgs = @("-p", "--output-format", "stream-json", "--verbose", "--strict-mcp-config",
                "--permission-mode", "dontAsk", "--allowedTools") + $tools
if ($MaxBudgetUsd -gt 0) { $claudeArgs += @("--max-budget-usd", "$MaxBudgetUsd") }

$out = $prompt | claude @claudeArgs 2>&1
$out | ForEach-Object { "$_" } | Set-Content $transcript -Encoding UTF8

# The last stream-json line is the result: the digest text, cost and turn count.
$result = $null
foreach ($line in ($out | ForEach-Object { "$_" } | Select-Object -Last 5)) {
    try { $obj = $line | ConvertFrom-Json; if ($obj.type -eq "result") { $result = $obj } } catch {}
}
if ($result) {
    $digest = Join-Path $digestDir "$date.md"
    Add-Content $digest ("`n<!-- $stamp -->`n" + $result.result) -Encoding UTF8
    Log ("Finished: {0}, {1} turns, `${2:N2}, {3:N0} min" -f $result.subtype, $result.num_turns,
         $result.total_cost_usd, ($result.duration_ms / 60000))
    $result.result | Add-Content $logFile -Encoding UTF8
} else {
    Log "Claude did not finish normally; see the transcript"
    $out | Select-Object -Last 10 | ForEach-Object { "$_" } | Add-Content $logFile -Encoding UTF8
}

# Azure (docs/postgres-mirror.md): once Postgres is the main database (phase 4), back it up to
# backups\jobs-<date>.db; before that, copy jobs.db into the Postgres shadow copy when
# settings.yaml has database.postgres_mirror: true. A failure is only logged.
$mirrorOut = & uv run python scripts/pg_mirror.py daily 2>&1 | ForEach-Object { "$_" }
$mirrorCode = $LASTEXITCODE
if ($mirrorOut) {
    if ($mirrorCode -eq 0) { Log "Postgres daily step done (backup or mirror sync)" }
    else { Log "WARNING: Postgres daily step exit code $mirrorCode (see logs\pg-mirror.jsonl)" }
    $mirrorOut | Where-Object { $_ -notmatch "UV_NATIVE_TLS" } | Add-Content $logFile -Encoding UTF8
}
# The Azure scrape job scores with the vault files saved in Postgres; keep them current.
$pushOut = & uv run python scripts/score_inputs.py push 2>&1 | ForEach-Object { "$_" }
if ($LASTEXITCODE -ne 0) { Log "WARNING: saving the scoring files to Postgres failed (exit $LASTEXITCODE)" }
$pushOut | Where-Object { $_ -notmatch "UV_NATIVE_TLS" } | Add-Content $logFile -Encoding UTF8
# dbt (docs/dbt-guide.md): rebuild the analytics schemas Power BI reads, and take the daily
# snapshot that keeps postings after the 30-day cleanup deletes them. Skipped until the project
# has a model or snapshot; a failure is only logged (full output in dbt\logs\dbt.log).
$dbtOut = & uv run python scripts/dbt.py daily 2>&1 | ForEach-Object { "$_" }
if ($LASTEXITCODE -ne 0) { Log "WARNING: dbt daily build failed (exit $LASTEXITCODE)" }
else { Log "dbt daily build done" }
$dbtOut | Where-Object { $_ -notmatch "UV_NATIVE_TLS" } | Select-Object -Last 15 | Add-Content $logFile -Encoding UTF8

# Nothing tracked should change during a run.
$tracked = git status --porcelain --untracked-files=no -- src tests prompts docs config scripts
if ($tracked) { Log "WARNING: tracked files changed during the run:"; $tracked | Add-Content $logFile -Encoding UTF8 }
Log "Done"

# Review the run and fix the pipeline where it went wrong, unless there was nothing to tailor.
if (-not $NoReview -and -not ($result -and $result.result -match "Nothing new to tailor")) {
    & (Join-Path $PSScriptRoot "run_tailoring_review.ps1") -Transcript $transcript
}
Remove-Item $runFile -ErrorAction SilentlyContinue
