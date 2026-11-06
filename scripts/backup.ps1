param([string]$Destination)
$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path $PSScriptRoot -Parent
if (-not $Destination) { $Destination = Join-Path $ProjectRoot ('.local/backups/drevo-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.sqlite3') }
Push-Location (Join-Path $ProjectRoot 'backend')
try { & '../.venv/Scripts/python.exe' -X utf8 -m app.cli backup $Destination; if ($LASTEXITCODE -ne 0) { throw 'Резервирование не выполнено.' } } finally { Pop-Location }
