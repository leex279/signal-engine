# Daily runner script for Windows Task Scheduler
$ErrorActionPreference = "Stop"
$RepoDir = Split-Path -Parent $PSScriptRoot
Set-Location $RepoDir
$env:PYTHONIOENCODING = "utf-8"
uv run signal-engine run --db data/signal.db --out digests
