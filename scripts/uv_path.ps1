# Dot-sourced by the scheduled-task wrappers: makes sure `uv` is on PATH, for this script and for
# the Bash shell Claude runs its commands in. A task started by Task Scheduler can get an older PATH
# than an interactive window (Oct 23 2026: the 9:00 run stopped at its first command with
# "uv: command not found"), so the user and machine PATH are read fresh from the registry and the
# usual install folders are tried as well. Returns $true when uv was found.

function Add-UvToPath {
    $fresh = @([Environment]::GetEnvironmentVariable("Path", "User"),
               [Environment]::GetEnvironmentVariable("Path", "Machine")) -join ";"
    $env:Path = "$env:Path;$fresh"
    $uv = Get-Command uv -ErrorAction SilentlyContinue
    $dir = if ($uv) { Split-Path -Parent $uv.Source } else {
        @("$env:USERPROFILE\.local\bin", "$env:USERPROFILE\.cargo\bin", "$env:LOCALAPPDATA\Microsoft\WinGet\Links",
          "$env:LOCALAPPDATA\Programs\uv") + @(Get-ChildItem "$env:LOCALAPPDATA\Programs\Python\*\Scripts", "$env:APPDATA\Python\*\Scripts" -Directory -ErrorAction SilentlyContinue | ForEach-Object FullName) |
            Where-Object { Test-Path (Join-Path $_ "uv.exe") } | Select-Object -First 1
    }
    if (-not $dir) { return $false }
    # First on PATH, so the Bash shell Claude starts inherits it too.
    $env:Path = "$dir;$env:Path"
    return $true
}
