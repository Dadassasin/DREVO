param([Parameter(Mandatory=$true)][string]$Source)
$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path $PSScriptRoot -Parent
$ResolvedSource = (Resolve-Path -LiteralPath $Source).Path
& "$PSScriptRoot/stop_all.ps1"
& "$PSScriptRoot/backup.ps1"
Push-Location (Join-Path $ProjectRoot 'backend')
try { & '../.venv/Scripts/python.exe' -X utf8 -m app.cli restore $ResolvedSource; if ($LASTEXITCODE -ne 0) { throw 'Восстановление не выполнено.' } } finally { Pop-Location }
Write-Host 'База восстановлена. Сессии и временные ссылки отозваны. Запустите start_server.bat.'
