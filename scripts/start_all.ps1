$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path $PSScriptRoot -Parent
$PythonExe = Join-Path $ProjectRoot '.venv/Scripts/python.exe'
$BackendPath = Join-Path $ProjectRoot 'backend'
$LocalPath = Join-Path $ProjectRoot '.local'
if (-not (Test-Path -LiteralPath $PythonExe)) { throw 'Сначала запустите install.bat.' }
New-Item -ItemType Directory -Force -Path $LocalPath | Out-Null
Push-Location $BackendPath
try {
    & $PythonExe -X utf8 -c "from app.config import Settings; s=Settings(); assert s.archive_root.is_dir(), 'Archive drive is not connected'; assert s.db_path.is_file(), 'Working database not found; connect the archive drive first'"
    if ($LASTEXITCODE -ne 0) { throw 'Архив или рабочая база недоступны. Подключите диск и проверьте пути в .env.' }
} finally { Pop-Location }
$PidFile = Join-Path $LocalPath 'processes.json'
$Processes = @{}
if (Test-Path -LiteralPath $PidFile) {
    $Saved = Get-Content -LiteralPath $PidFile -Raw | ConvertFrom-Json
    foreach ($Entry in $Saved.PSObject.Properties) {
        $Existing = Get-CimInstance Win32_Process -Filter "ProcessId = $($Entry.Value)" -ErrorAction SilentlyContinue
        if ($Existing -and $Existing.ExecutablePath -eq $PythonExe.Replace('/','\') -and $Existing.CommandLine -like '*app.*') { $Processes[$Entry.Name] = $Entry.Value }
    }
}
if (-not $Processes.ContainsKey('server')) {
    $Process = Start-Process -FilePath $PythonExe -ArgumentList @('-X','utf8','-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8000','--no-access-log','--no-proxy-headers') -WorkingDirectory $BackendPath -WindowStyle Hidden -RedirectStandardOutput (Join-Path $LocalPath 'server.log') -RedirectStandardError (Join-Path $LocalPath 'server-error.log') -PassThru
    $Processes['server'] = $Process.Id
}
if (-not $Processes.ContainsKey('sync')) {
    $Process = Start-Process -FilePath $PythonExe -ArgumentList @('-X','utf8','-m','app.github_sync.worker') -WorkingDirectory $BackendPath -WindowStyle Hidden -RedirectStandardOutput (Join-Path $LocalPath 'sync.log') -RedirectStandardError (Join-Path $LocalPath 'sync-error.log') -PassThru
    $Processes['sync'] = $Process.Id
}
$Processes | ConvertTo-Json | Set-Content -LiteralPath $PidFile -Encoding UTF8
Write-Host 'ДРЕВО: http://127.0.0.1:8000 — сервер и синхронизатор запущены в фоне.'
