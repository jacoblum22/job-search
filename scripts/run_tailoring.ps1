# Scheduled-task wrapper: daily tailoring run (docs/tailoring-runbook.md).
# Registered as the "JobSearch-Tailoring" Windows Task Scheduler task.
# Claude drafts a resume and cover letter for the best new A-tier jobs and stops
# at "Ready for review" on the dashboard. It never applies, sends, commits or pushes.
#
# With -Scrape (what the scheduled task passes) it first runs a full scrape (scripts/aggregate.py,
# every source) so the queue sees today's postings; the queue then rescores every job. A run
# started by hand or from the dashboard's Run button skips the scrape and tailors from the jobs
# already in the database (Jake, Oct 29 2026). The Azure job scrapes every
# morning (docs/azure-scrape-job.md), so when a full run finished in the last 6 hours the
# scrape here fetches only the sources that block Azure (settings.yaml cloud_sources), and
# does the full scrape only when that job didn't run. -JobId / -ResumeOnly runs never scrape,
# even with -Scrape, since they don't pick new jobs (-NoScrape is still accepted; it's the default). If the scrape fails
# the run still tailors from the jobs already in the database and logs why.
#
# Test on one job:   .\scripts\run_tailoring.ps1 -Limit 1   (or -JobId 812)
# Normal daily run:  .\scripts\run_tailoring.ps1 -Scrape    (the scheduled task; tailor.daily_cap jobs)
# By hand, no scrape: .\scripts\run_tailoring.ps1
# Waiting rounds only (repair or letter rounds on applications up for review, no new jobs):
#                    .\scripts\run_tailoring.ps1 -ResumeOnly
# -Parallel N (2 by default) runs up to N Claude sessions at once: waiting rounds and unfinished
# folders start while the scrape runs, then a session per company for the queue's new jobs
# (docs/tailoring-runbook.md, "Parallel sessions"). -Parallel 1 is one session for everything,
# as -JobId and -ResumeOnly runs always are.
# Afterwards run_tailoring_review.ps1 reviews the logs and opens a PR for any pipeline
# fixes (docs/run-review-task.md); -NoReview skips that.

param(
    [int]$JobId = 0,
    [int]$Limit = 0,
    [double]$MaxBudgetUsd = 0,
    [switch]$NoReview,
    [switch]$Scrape,
    [switch]$NoScrape,
    [switch]$ResumeOnly,
    [int]$Parallel = 2
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
Log "Starting tailoring run ($mode)"
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
$scrapeLog = Join-Path $projectRoot "logs\full_aggregate.log"
$stdoutTmp = Join-Path $env:TEMP "job-tailoring-scrape-stdout.log"
$stderrTmp = Join-Path $env:TEMP "job-tailoring-scrape-stderr.log"

function Start-Scrape {
    "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Starting full aggregation (before tailoring)" | Add-Content $scrapeLog
    Log "Scraping every source before picking jobs (log: logs\full_aggregate.log)"
    $script:scrapeStart = Get-Date
    try {
        # --wait-lock: if another scrape (the Azure job, the email check) is mid-way, wait for
        # it (up to 30 min) instead of skipping the scrape; --skip-if-fresh: after a full run in
        # the last 6 hours, fetch only what the Azure job leaves here (exit 4 if that's nothing).
        $p = Start-Process -FilePath (Join-Path $projectRoot ".venv\Scripts\python.exe") `
            -ArgumentList "scripts/aggregate.py", "--wait-lock", "1800", "--skip-if-fresh", "6" `
            -WorkingDirectory $projectRoot `
            -RedirectStandardOutput $stdoutTmp -RedirectStandardError $stderrTmp `
            -NoNewWindow -PassThru
        $null = $p.Handle   # without this, ExitCode stays empty for a process not started with -Wait
        return $p
    } catch {
        $script:scrapeError = "not started: $($_.Exception.Message)"
        return $null
    }
}

function Complete-Scrape($proc) {
    $code = if ($proc) { $proc.WaitForExit(); $proc.ExitCode } else { $script:scrapeError }
    Get-Content $stdoutTmp, $stderrTmp -ErrorAction SilentlyContinue | Add-Content $scrapeLog
    Remove-Item $stdoutTmp, $stderrTmp -ErrorAction SilentlyContinue
    "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Done (exit code $code)" | Add-Content $scrapeLog
    $mins = ((Get-Date) - $script:scrapeStart).TotalMinutes
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
function Sync-BrowserQueue {
    $bqOut = & (Join-Path $projectRoot ".venv\Scripts\python.exe") scripts\browser_queue.py sync 2>&1 | ForEach-Object { "$_" }
    if ($LASTEXITCODE -ne 0) { Log "WARNING: browser queue sync failed (exit $LASTEXITCODE)" }
    $bqOut | Where-Object { $_ -notmatch "UV_NATIVE_TLS" } | ForEach-Object { Log $_ }
}

# The prompt is everything between the two markers in the runbook; {SCOPE} says which part of
# the run this Claude session does.
$doc = Get-Content (Join-Path $projectRoot "docs\tailoring-runbook.md") -Raw -Encoding UTF8
$basePrompt = ($doc -split "<!-- prompt start -->", 2)[1]
$basePrompt = ($basePrompt -split "<!-- prompt end -->", 2)[0]
$basePrompt = $basePrompt.Replace("{DATE}", $date).Replace("{QUEUE}", $queueCmd)

$tools = @(
    "Read", "Glob", "Grep", "WebSearch", "Agent",
    "Edit(materials/applications/**)", "Edit(materials/companies/**)",
    "Bash(uv run python -m src.tailor:*)"
)
# --strict-mcp-config with no --mcp-config: no connectors (Gmail, Calendar...) are loaded.
$claudeArgs = @("-p", "--output-format", "stream-json", "--verbose", "--strict-mcp-config",
                "--permission-mode", "dontAsk", "--allowedTools") + $tools
if ($MaxBudgetUsd -gt 0) { $claudeArgs += @("--max-budget-usd", "$MaxBudgetUsd") }

# One Claude session runs as a background job (its own PowerShell process), so several can run
# at once. Each writes its own transcript.
$sessionBlock = {
    param($root, $prompt, $cliArgs, $transcriptPath)
    $cliArgs = @($cliArgs)   # a job hands arrays over as lists; splatting needs an array
    Set-Location $root
    $enc = New-Object System.Text.UTF8Encoding $false
    $OutputEncoding = $enc
    try { [Console]::OutputEncoding = $enc } catch {}
    $out = $prompt | claude @cliArgs 2>&1
    $out | ForEach-Object { "$_" } | Set-Content $transcriptPath -Encoding UTF8
}
$sessions = @()

function Start-Session($label, $scope) {
    $n = $script:sessions.Count + 1
    $path = if ($n -eq 1 -and $label -eq "all") { $transcript } else { Join-Path $logDir "${stamp}_$n-$label.jsonl" }
    $prompt = $basePrompt.Replace("{SCOPE}", $scope)
    $job = Start-Job -ScriptBlock $sessionBlock -ArgumentList @($projectRoot, $prompt, $claudeArgs, $path)
    $s = [pscustomobject]@{ Label = $label; Transcript = $path; Job = $job; Result = $null; Done = $false }
    $script:sessions += $s
    Log "Started Claude session $n ($label); transcript $path"
    return $s
}

function Complete-Session($s) {
    Receive-Job $s.Job -ErrorAction SilentlyContinue | Out-Null
    Remove-Job $s.Job -Force -ErrorAction SilentlyContinue
    $s.Done = $true
    $lines = if (Test-Path $s.Transcript) { Get-Content $s.Transcript -Encoding UTF8 } else { @() }
    # The last stream-json line is the result: the digest text, cost and turn count.
    foreach ($line in ($lines | Select-Object -Last 5)) {
        try { $obj = $line | ConvertFrom-Json; if ($obj.type -eq "result") { $s.Result = $obj } } catch {}
    }
    if ($s.Result) {
        $digest = Join-Path $digestDir "$date.md"
        Add-Content $digest ("`n<!-- $stamp $($s.Label) -->`n" + $s.Result.result) -Encoding UTF8
        Log ("Finished ({0}): {1}, {2} turns, `${3:N2}, {4:N0} min" -f $s.Label, $s.Result.subtype,
             $s.Result.num_turns, $s.Result.total_cost_usd, ($s.Result.duration_ms / 60000))
        $s.Result.result | Add-Content $logFile -Encoding UTF8
    } else {
        Log "Claude session ($($s.Label)) did not finish normally; see $($s.Transcript)"
        $lines | Select-Object -Last 10 | Add-Content $logFile -Encoding UTF8
    }
}

function Get-JsonList($cmdArgs) {
    # stdout only: uv and the CLI log to stderr.
    $raw = & uv run python -m src.tailor @cmdArgs 2>$null | Out-String
    if ($LASTEXITCODE -ne 0) { Log "WARNING: 'src.tailor $($cmdArgs -join ' ')' failed (exit $LASTEXITCODE)"; return @() }
    # PowerShell 5.1's ConvertFrom-Json returns a JSON list as one object; the pipe unrolls it.
    try { return @($raw | ConvertFrom-Json | ForEach-Object { $_ }) } catch { Log "WARNING: could not read the output of 'src.tailor $($cmdArgs -join ' ')'"; return @() }
}

# Folders of one company go to the same session, one after another, so two sessions never
# research the same company folder at once.
function Group-ByCompany($folders) {
    $groups = [ordered]@{}
    foreach ($f in $folders) {
        $company = ""
        try { $company = (Get-Content (Join-Path $f "app.json") -Raw -Encoding UTF8 | ConvertFrom-Json).company } catch {}
        $key = ($company -replace "[^A-Za-z0-9]+", "-").ToLower()
        if (-not $key) { $key = $f }
        if (-not $groups.Contains($key)) { $groups[$key] = @() }
        $groups[$key] += $f
    }
    # Objects, not nested arrays, which PowerShell would flatten.
    return @($groups.Values | ForEach-Object { [pscustomobject]@{ Folders = @($_) } })
}

function Get-FolderScope($folders) {
    $list = ($folders | ForEach-Object { "- `"$((Resolve-Path $_).Path)`"" }) -join "`n"
    return "Other Claude sessions are tailoring other folders at the same time. Skip Step A " +
        "entirely: do not glob for unfinished folders, and do not run ``pending`` or the queue. Do " +
        "Step B for these folders only, in this order (for a folder that already has some outputs, " +
        "start at the first step whose output file is missing):`n$list`nNever read or change any " +
        "other application folder. End with the digest for these folders only."
}

$parallelRun = $Parallel -gt 1 -and -not $ResumeOnly -and $JobId -le 0
$doScrape = $Scrape -and -not $NoScrape -and -not $ResumeOnly -and $JobId -le 0

if (-not $parallelRun) {
    # One session does the whole run, as the runbook's Step A and Step B describe.
    if ($doScrape) { Complete-Scrape (Start-Scrape) }
    Sync-BrowserQueue
    $s = Start-Session "all" "Do all of Step A and Step B below."
    Wait-Job $s.Job | Out-Null
    Complete-Session $s
} else {
    # Up to $Parallel sessions at once. Waiting rounds and folders an earlier run left unfinished
    # don't depend on today's postings, so they start while the scrape runs; today's new jobs
    # are queued once it finishes, a session per company.
    Log "Running up to $Parallel Claude sessions at once"
    $todo = New-Object System.Collections.ArrayList
    $unfinished = @(Get-ChildItem (Join-Path $projectRoot "materials\applications") -Directory -ErrorAction SilentlyContinue |
        Where-Object {
            $app = Join-Path $_.FullName "app.json"
            (Test-Path $app) -and ((Get-Content $app -Raw -Encoding UTF8 | ConvertFrom-Json).status -eq "shortlisted")
        } | ForEach-Object { $_.FullName })
    $waiting = @(Get-JsonList @("pending"))
    if ($waiting.Count -gt 0) {
        [void]$todo.Add(@{ Label = "waiting"; Scope = "Other Claude sessions are drafting new jobs at the " +
            "same time. Do Step A step 2 only (the waiting rounds from ``pending``); skip Step A steps 1 " +
            "and 3 and never touch a folder whose status is ``shortlisted``. End with the digest for " +
            "these folders only." })
    }
    foreach ($g in @(Group-ByCompany $unfinished)) {
        [void]$todo.Add(@{ Label = "unfinished"; Scope = (Get-FolderScope $g.Folders) })
    }
    if ($unfinished.Count -gt 0) { Log "$($unfinished.Count) unfinished folder(s) from an earlier run" }

    $scrapeProc = if ($doScrape) { Start-Scrape } else { $null }
    $scrapeDone = -not $doScrape -or -not $scrapeProc
    if ($doScrape -and -not $scrapeProc) { Complete-Scrape $null }
    $queued = $false
    while ($true) {
        if (-not $scrapeDone -and $scrapeProc.HasExited) { Complete-Scrape $scrapeProc; $scrapeDone = $true }
        if ($scrapeDone -and -not $queued) {
            $queued = $true
            Sync-BrowserQueue
            $qArgs = @("queue") + $(if ($Limit -gt 0) { @("--limit", "$Limit") } else { @() })
            $new = @(Get-JsonList $qArgs)
            Log "Queue: $($new.Count) new job(s)"
            foreach ($g in @(Group-ByCompany $new)) {
                [void]$todo.Add(@{ Label = "new"; Scope = (Get-FolderScope $g.Folders) })
            }
        }
        foreach ($s in @($sessions | Where-Object { -not $_.Done -and $_.Job.State -in @("Completed", "Failed", "Stopped") })) { Complete-Session $s }
        $running = @($sessions | Where-Object { -not $_.Done }).Count
        while ($running -lt $Parallel -and $todo.Count -gt 0) {
            $t = $todo[0]; $todo.RemoveAt(0)
            Start-Session $t.Label $t.Scope | Out-Null
            $running++
            Start-Sleep -Seconds 5   # stagger the starts a little
        }
        if ($queued -and $running -eq 0 -and $todo.Count -eq 0) { break }
        Start-Sleep -Seconds 10
    }
    if (-not $sessions) { Log "Nothing new to tailor"; Add-Content (Join-Path $digestDir "$date.md") "`n<!-- $stamp -->`nNothing new to tailor" -Encoding UTF8 }
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
# Snowflake (docs/snowflake-guide.md): copy the tables to Azure storage, load them into Snowflake
# and build the same dbt models there. Each step is skipped until it's set up in .env; a failure
# is only logged.
$sfOut = & uv run python scripts/snowflake_sync.py daily 2>&1 | ForEach-Object { "$_" }
if ($LASTEXITCODE -ne 0) { Log "WARNING: Snowflake daily step failed (exit $LASTEXITCODE)" }
else { Log "Snowflake daily step done" }
$sfOut | Where-Object { $_ -notmatch "UV_NATIVE_TLS" } | Select-Object -Last 15 | Add-Content $logFile -Encoding UTF8

# Nothing tracked should change during a run.
$tracked = git status --porcelain --untracked-files=no -- src tests prompts docs config scripts
if ($tracked) { Log "WARNING: tracked files changed during the run:"; $tracked | Add-Content $logFile -Encoding UTF8 }
Log "Done"

# Review the run and fix the pipeline where it went wrong, unless there was nothing to tailor.
$reviewed = @($sessions | Where-Object { -not ($_.Result -and $_.Result.result -match "Nothing new to tailor") } |
    Where-Object { Test-Path $_.Transcript } | ForEach-Object { $_.Transcript })
if (-not $NoReview -and $reviewed.Count -gt 0) {
    & (Join-Path $PSScriptRoot "run_tailoring_review.ps1") -Transcript $reviewed
}
Remove-Item $runFile -ErrorAction SilentlyContinue
