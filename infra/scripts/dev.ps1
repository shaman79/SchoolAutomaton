# SchoolAutomaton — local dev (Windows): backend (uvicorn --reload) + frontend (vite) in two windows.
# Usage:  ./infra/scripts/dev.ps1
$ErrorActionPreference = "Stop"
$root = Resolve-Path "$PSScriptRoot/../.."

if (-not (Test-Path "$root/.env")) { Copy-Item "$root/.env.example" "$root/.env" }

$backend = @"
Set-Location '$root/backend'
if (-not (Test-Path .venv)) { python -m venv .venv }
./.venv/Scripts/python.exe -m pip install -r requirements-dev.txt
./.venv/Scripts/python.exe -m uvicorn app.main:app --reload --port 8000
"@
$frontend = @"
Set-Location '$root/frontend'
if (-not (Test-Path node_modules)) { npm install }
npm run dev
"@

Start-Process powershell -ArgumentList "-NoExit", "-Command", $backend
Start-Process powershell -ArgumentList "-NoExit", "-Command", $frontend
Write-Host "Backend → http://localhost:8000   Frontend → http://localhost:5173" -ForegroundColor Green
