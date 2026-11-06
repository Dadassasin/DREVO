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
Write-Host 'Процессы ДРЕВО остановлены.'
