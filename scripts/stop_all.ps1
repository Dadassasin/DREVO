$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path $PSScriptRoot -Parent
$PythonExe = (Join-Path $ProjectRoot '.venv/Scripts/python.exe').Replace('/','\')
$PidFile = Join-Path $ProjectRoot '.local/processes.json'
if (Test-Path -LiteralPath $PidFile) {
    $Saved = Get-Content -LiteralPath $PidFile -Raw | ConvertFrom-Json
    foreach ($Entry in $Saved.PSObject.Properties) {
        $Existing = Get-CimInstance Win32_Process -Filter "ProcessId = $($Entry.Value)" -ErrorAction SilentlyContinue
        if ($Existing -and $Existing.ExecutablePath -eq $PythonExe -and $Existing.CommandLine -like '*app.*') { Stop-Process -Id $Existing.ProcessId }
    }
    Remove-Item -LiteralPath $PidFile
}
Push-Location (Join-Path $ProjectRoot 'backend')
try {
    $FinalizeDatabase = @'
from app.config import Settings, ROOT
from app.services.backup import backup
import sqlite3
s = Settings()
if s.data_dir.resolve().is_relative_to(s.archive_root.resolve()) and s.db_path.is_file():
    with sqlite3.connect(s.db_path) as db:
        result = db.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()
        assert result[0] == 0, 'Database is still busy; do not disconnect the drive'
    db.close()
    backup(s, ROOT / '.local/backups/external-last-stop.sqlite3')
'@
    & $PythonExe -X utf8 -c $FinalizeDatabase
    if ($LASTEXITCODE -ne 0) { throw 'Не удалось завершить работу с базой. Пока не отключайте внешний диск.' }
} finally { Pop-Location }
Write-Host 'Процессы ДРЕВО остановлены.'
