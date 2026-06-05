# SchoolAutomaton — update an existing deployment (Windows): pull, rebuild, restart, prune.
# Usage:  ./infra/scripts/update.ps1
$ErrorActionPreference = "Stop"
$root = Resolve-Path "$PSScriptRoot/../.."
Set-Location $root

if (Test-Path ".git") {
    Write-Host "Pulling latest changes..." -ForegroundColor Cyan
    git pull --ff-only
}

Write-Host "Rebuilding images..." -ForegroundColor Cyan
docker compose build
if ($LASTEXITCODE -ne 0) { throw "build failed" }

Write-Host "Recreating containers (data volume preserved)..." -ForegroundColor Cyan
docker compose up -d
if ($LASTEXITCODE -ne 0) { throw "up failed" }

docker image prune -f | Out-Null
Write-Host "Update complete. App: http://localhost:8080" -ForegroundColor Green
