# Scheduled-task wrapper: daily skills-list review (docs/skills-review-task.md).
# Registered as the "JobSearch-SkillsReview" Windows Task Scheduler task.
# Claude edits a fresh worktree of origin/jake; this script runs the tests,
# commits, pushes and opens a PR into jake. Nothing is merged automatically.

$projectRoot = Split-Path -Parent $PSScriptRoot
$date = Get-Date -Format "yyyy-MM-dd"
$branch = "skills-review/$date"
$worktree = Join-Path (Split-Path -Parent $projectRoot) "job-search-skills-review"
$logFile = Join-Path $projectRoot "logs\skills_review.log"
New-Item -ItemType Directory -Force -Path (Split-Path $logFile) | Out-Null

function Log($msg) { "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $msg" | Add-Content $logFile }

Log "Starting skills review"
. (Join-Path $PSScriptRoot "uv_path.ps1")
if (-not (Add-UvToPath)) { Log "ERROR: uv not found on PATH or in the usual install folders; nothing ran"; exit 1 }
Set-Location $projectRoot
git fetch origin jake 2>&1 | Out-Null
if (Test-Path $worktree) { git worktree remove --force $worktree 2>&1 | Out-Null }
git branch -D $branch 2>&1 | Out-Null
git worktree add -b $branch $worktree origin/jake 2>&1 | Add-Content $logFile
if (-not (Test-Path $worktree)) { Log "Could not create worktree"; exit 1 }

$db = Join-Path $env:TEMP "skills-review-jobs.db"
Copy-Item (Join-Path $projectRoot "jobs.db") $db -Force

# The prompt is everything after the "---" under "## Prompt".
$doc = Get-Content (Join-Path $worktree "docs\skills-review-task.md") -Raw
$prompt = ($doc -split "## Prompt\s*\r?\n\s*---\s*\r?\n", 2)[1]
$prompt = $prompt.Replace("{DATE}", $date).Replace("{BRANCH}", $branch).Replace("{MAIN}", $projectRoot).Replace("{DB}", $db)

Set-Location $worktree
uv sync -q 2>&1 | Out-Null
$out = $prompt | claude -p --add-dir $projectRoot --permission-mode acceptEdits `
    --allowedTools "Read" "Grep" "Glob" "Edit" "Write" "Bash(uv run python:*)" "Bash(uv run pytest:*)" 2>&1
$out | Add-Content $logFile

$bodyFile = Join-Path $worktree ".skills-review-pr.md"
$changed = git status --porcelain -- src tests
if (-not $changed) {
    Log "No skills added"
} else {
    uv run pytest -q 2>&1 | Tee-Object -Variable testOut | Out-Null
    $testOut | Select-Object -Last 3 | Add-Content $logFile
    if ($LASTEXITCODE -ne 0) {
        Log "Tests failed; nothing pushed. Worktree left at $worktree"
        Set-Location $projectRoot
        exit 1
    }
    $body = if (Test-Path $bodyFile) { Get-Content $bodyFile -Raw } else { "Daily skills review $date." }
    Remove-Item $bodyFile -ErrorAction SilentlyContinue
    git add src tests
    git commit -q -m "Skills review ${date}: add skills from new postings" 2>&1 | Add-Content $logFile
    git push -q -u origin $branch 2>&1 | Add-Content $logFile
    $bodyTmp = Join-Path $env:TEMP "skills-review-pr.md"
    Set-Content $bodyTmp $body
    if (Get-Command gh -ErrorAction SilentlyContinue) {
        gh pr create --base jake --head $branch --title "Skills review ${date}" --body-file $bodyTmp 2>&1 | Add-Content $logFile
    } else {
        Log "gh not found; open https://github.com/jacoblum22/job-search/compare/jake...$branch"
    }
    Remove-Item $bodyTmp -ErrorAction SilentlyContinue
}

Set-Location $projectRoot
git worktree remove --force $worktree 2>&1 | Out-Null
if (-not $changed) { git branch -D $branch 2>&1 | Out-Null }
Remove-Item $db -ErrorAction SilentlyContinue
Log "Done"
