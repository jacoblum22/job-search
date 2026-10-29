# Post-run review (docs/run-review-task.md): after a tailoring run, Claude reads
# the run's log and fixes pipeline bugs in a fresh worktree of origin/jake. This
# script runs the tests, commits, pushes and opens a PR into jake. Nothing is
# merged automatically. Called by run_tailoring.ps1; can also be run by hand:
#   .\scripts\run_tailoring_review.ps1 -Transcript logs\tailoring\2026-10-20_0139.jsonl
# A parallel run passes every session's transcript (-Transcript a.jsonl, b.jsonl); the
# summary Claude reads has one section per session.

param([Parameter(Mandatory = $true)][string[]]$Transcript)

$projectRoot = Split-Path -Parent $PSScriptRoot
$date = Get-Date -Format "yyyy-MM-dd"
$stamp = Get-Date -Format "yyyy-MM-dd_HHmm"
$branch = "run-review/$stamp"
$worktree = Join-Path (Split-Path -Parent $projectRoot) "job-search-run-review"
$logFile = Join-Path $projectRoot "logs\tailoring_review.log"
$notesDir = Join-Path $projectRoot "materials\tailor\run-reviews"
New-Item -ItemType Directory -Force -Path (Split-Path $logFile), $notesDir | Out-Null

function Log($msg) { "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $msg" | Add-Content $logFile -Encoding UTF8 }

$utf8 = New-Object System.Text.UTF8Encoding $false
$OutputEncoding = $utf8
[Console]::OutputEncoding = $utf8

Set-Location $projectRoot
$Transcript = @($Transcript | ForEach-Object { (Resolve-Path $_).Path })
Log "Starting run review of $($Transcript -join ', ')"
. (Join-Path $PSScriptRoot "uv_path.ps1")
if (-not (Add-UvToPath)) { Log "ERROR: uv not found on PATH or in the usual install folders; nothing ran"; exit 1 }
git fetch origin jake 2>&1 | Out-Null
if (Test-Path $worktree) { git worktree remove --force $worktree 2>&1 | Out-Null }
git branch -D $branch 2>&1 | Out-Null
git worktree add -b $branch $worktree origin/jake 2>&1 | Add-Content $logFile -Encoding UTF8
if (-not (Test-Path $worktree)) { Log "Could not create worktree"; exit 1 }

# A readable copy of the transcript, inside the worktree so Claude may read it (never committed).
$summary = Join-Path $worktree ".run-summary.md"
if ($Transcript.Count -eq 1) {
    uv run python scripts\transcript_summary.py $Transcript[0] 2>$null | Set-Content $summary -Encoding UTF8
} else {
    Set-Content $summary "" -Encoding UTF8
    $n = 0
    foreach ($t in $Transcript) {
        $n++
        "# Session $n of $($Transcript.Count): $(Split-Path -Leaf $t)`n" | Add-Content $summary -Encoding UTF8
        uv run python scripts\transcript_summary.py $t 2>$null | Add-Content $summary -Encoding UTF8
        "" | Add-Content $summary -Encoding UTF8
    }
}
# What earlier reviews found, by area, so this one can tell a recurring problem from a new one.
$tallyCsv = Join-Path $notesDir "tally.csv"
$tallyView = Join-Path $worktree ".run-tally.md"
uv run python scripts\review_tally.py show $tallyCsv 2>$null | Set-Content $tallyView -Encoding UTF8

$doc = Get-Content (Join-Path $worktree "docs\run-review-task.md") -Raw -Encoding UTF8
$prompt = ($doc -split "<!-- prompt start -->", 2)[1]
$prompt = ($prompt -split "<!-- prompt end -->", 2)[0]
$prompt = $prompt.Replace("{DATE}", $date).Replace("{BRANCH}", $branch).Replace("{MAIN}", $projectRoot).Replace("{SUMMARY}", $summary).Replace("{TALLY}", $tallyView)

Set-Location $worktree
uv sync -q 2>&1 | Out-Null
$tools = @(
    "Read", "Glob", "Grep",
    "Edit(src/**)", "Edit(tests/**)", "Edit(prompts/**)", "Edit(docs/**)", "Edit(config/**)",
    "Edit(.run-review-pr.md)", "Edit(.run-review-notes.md)", "Edit(.run-review-tally.json)",
    "Bash(uv run pytest:*)", "Bash(uv run python -c:*)"
)
$claudeArgs = @("-p", "--output-format", "stream-json", "--verbose", "--strict-mcp-config",
                "--add-dir", $projectRoot, "--permission-mode", "dontAsk", "--allowedTools") + $tools
$out = $prompt | claude @claudeArgs 2>&1
$out | ForEach-Object { "$_" } | Set-Content (Join-Path $projectRoot "logs\tailoring\review_$stamp.jsonl") -Encoding UTF8
foreach ($line in ($out | ForEach-Object { "$_" } | Select-Object -Last 5)) {
    try { $obj = $line | ConvertFrom-Json; if ($obj.type -eq "result") { $obj.result | Add-Content $logFile -Encoding UTF8 } } catch {}
}

$notes = Join-Path $worktree ".run-review-notes.md"
if (Test-Path $notes) { Copy-Item $notes (Join-Path $notesDir "$stamp.md") -Force }
$tallyJson = Join-Path $worktree ".run-review-tally.json"
if (Test-Path $tallyJson) {
    uv run python scripts\review_tally.py add $tallyJson $tallyCsv $stamp 2>&1 | Add-Content $logFile -Encoding UTF8
}

$bodyFile = Join-Path $worktree ".run-review-pr.md"
# Claude is told not to commit, but count its commits too, so a fix is never thrown away.
$changed = git status --porcelain -- src tests prompts docs config
$commits = [int](git rev-list --count origin/jake..HEAD)
$pushed = $false
if (-not $changed -and $commits -eq 0) {
    Log "No code changes"
} else {
    uv run pytest -q 2>&1 | Tee-Object -Variable testOut | Out-Null
    $testOut | Select-Object -Last 3 | ForEach-Object { "$_" } | Add-Content $logFile -Encoding UTF8
    if ($LASTEXITCODE -ne 0) {
        Log "Tests failed; nothing pushed. Worktree left at $worktree"
        Set-Location $projectRoot
        exit 1
    }
    $body = if (Test-Path $bodyFile) { Get-Content $bodyFile -Raw -Encoding UTF8 } else { "Post-run review $stamp." }
    if ($changed) {
        git add src tests prompts docs config
        git commit -q -m "Run review ${stamp}: fix problems from the tailoring run" 2>&1 | Add-Content $logFile -Encoding UTF8
    }
    git push -q -u origin $branch 2>&1 | Add-Content $logFile -Encoding UTF8
    $pushed = $true
    $bodyTmp = Join-Path $env:TEMP "run-review-pr.md"
    Set-Content $bodyTmp $body -Encoding UTF8
    if (Get-Command gh -ErrorAction SilentlyContinue) {
        gh pr create --base jake --head $branch --title "Run review ${stamp}" --body-file $bodyTmp 2>&1 | Add-Content $logFile -Encoding UTF8
    } else {
        Log "gh not found; open https://github.com/jacoblum22/job-search/compare/jake...$branch"
    }
    Remove-Item $bodyTmp -ErrorAction SilentlyContinue
}

Set-Location $projectRoot
git worktree remove --force $worktree 2>&1 | Out-Null
if (-not $pushed) { git branch -D $branch 2>&1 | Out-Null }
Log "Done"
