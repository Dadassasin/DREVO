$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path $PSScriptRoot -Parent
Invoke-RestMethod 'http://127.0.0.1:8000/health'
Push-Location (Join-Path $ProjectRoot 'backend')
try { & '../.venv/Scripts/python.exe' -X utf8 -m app.cli check } finally { Pop-Location }
Get-Process cloudflared -ErrorAction SilentlyContinue | Select-Object ProcessName,Id
