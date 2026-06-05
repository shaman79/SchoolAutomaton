# SchoolAutomaton — first-time / full deploy (Windows). Builds images and starts the stack.
# Usage:  ./infra/scripts/deploy.ps1
$ErrorActionPreference = "Stop"
$root = Resolve-Path "$PSScriptRoot/../.."
Set-Location $root

if (-not (Test-Path ".env")) {
    Write-Host "No .env found — creating from .env.example. EDIT IT before going to production!" -ForegroundColor Yellow
    Copy-Item ".env.example" ".env"
}

Write-Host "Building images..." -ForegroundColor Cyan
docker compose build
if ($LASTEXITCODE -ne 0) { throw "docker compose build failed" }

Write-Host "Starting stack..." -ForegroundColor Cyan
docker compose up -d
if ($LASTEXITCODE -ne 0) { throw "docker compose up failed" }

Write-Host "`nSchoolAutomaton is up:" -ForegroundColor Green
Write-Host "  App:   http://localhost:8080"
Write-Host "  API:   http://localhost:8080/api/v1   (docs: backend container /docs)"
Write-Host "  Admin: http://localhost:8080/admin/login"
