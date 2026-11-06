param([string]$PythonVersion = '3')
$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path $PSScriptRoot -Parent
Set-Location $ProjectRoot
if (-not (Get-Command py -ErrorAction SilentlyContinue)) { throw 'Установите Python 3.12+ с python.org (Python Launcher).' }
$Version = & py "-$PythonVersion" -c "import sys; print(sys.version_info >= (3,12))"
if ($Version -ne 'True') { throw 'Требуется Python 3.12 или новее.' }
if (-not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) { throw 'Установите Node.js 22.12+.' }
if (-not (Test-Path -LiteralPath '.venv/Scripts/python.exe')) { & py "-$PythonVersion" -m venv .venv }
if ($LASTEXITCODE -ne 0) { throw 'Не удалось создать Python environment.' }
& '.venv/Scripts/python.exe' -m pip install -r backend/requirements.lock.txt
if ($LASTEXITCODE -ne 0) { throw 'Не удалось установить Python-зависимости.' }
if (-not (Test-Path -LiteralPath '.env')) { Copy-Item -LiteralPath '.env.example' -Destination '.env' }
Push-Location backend
try {
    & '../.venv/Scripts/python.exe' -X utf8 -m app.cli bootstrap
    if ($LASTEXITCODE -ne 0) { throw 'Не удалось подготовить БД.' }
} finally { Pop-Location }
Push-Location frontend
try {
    & npm.cmd ci
    if ($LASTEXITCODE -ne 0) { throw 'Не удалось установить frontend.' }
    & npm.cmd run build
    if ($LASTEXITCODE -ne 0) { throw 'Не удалось собрать frontend.' }
} finally { Pop-Location }
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$PSScriptRoot/protect_local.ps1"
Write-Host 'Установка завершена. Запустите start_server.bat. Код: .local/INITIAL-ACCESS.txt.'
