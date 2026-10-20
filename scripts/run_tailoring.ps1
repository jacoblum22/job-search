# Scheduled-task wrapper: daily tailoring run (docs/tailoring-runbook.md).
# Registered as the "JobSearch-Tailoring" Windows Task Scheduler task.
# Claude drafts a resume and cover letter for the best new A-tier jobs and stops
# at "Ready for review" on the dashboard. It never applies, sends, commits or pushes.
#
# Test on one job:   .\scripts\run_tailoring.ps1 -Limit 1   (or -JobId 812)
# Normal daily run:  .\scripts\run_tailoring.ps1            (tailor.daily_cap jobs)

param(
    [int]$JobId = 0,
    [int]$Limit = 0,
    [double]$MaxBudgetUsd = 0
)

$projectRoot = Split-Path -Parent $PSScriptRoot
$date = Get-Date -Format "yyyy-MM-dd"
$stamp = Get-Date -Format "yyyy-MM-dd_HHmm"
$logDir = Join-Path $projectRoot "logs\tailoring"
$logFile = Join-Path $projectRoot "logs\tailoring.log"
$transcript = Join-Path $logDir "$stamp.jsonl"
$digestDir = Join-Path $projectRoot "materials\tailor\digests"
New-Item -ItemType Directory -Force -Path $logDir, $digestDir | Out-Null

function Log($msg) { "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $msg" | Add-Content $logFile }

# PowerShell 5.1 pipes text to native programs as ASCII unless told otherwise.
$utf8 = New-Object System.Text.UTF8Encoding $false
$OutputEncoding = $utf8
[Console]::OutputEncoding = $utf8

Set-Location $projectRoot
if ($JobId -gt 0) {
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

uv sync -q 2>&1 | Out-Null

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
$claudeArgs = @("-p", "--output-format", "stream-json", "--verbose",
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
    $result.result | Add-Content $logFile
} else {
    Log "Claude did not finish normally; see the transcript"
    $out | Select-Object -Last 10 | ForEach-Object { "$_" } | Add-Content $logFile
}

# Nothing tracked should change during a run.
$tracked = git status --porcelain --untracked-files=no -- src tests prompts docs config scripts
if ($tracked) { Log "WARNING: tracked files changed during the run:"; $tracked | Add-Content $logFile }
Log "Done"
