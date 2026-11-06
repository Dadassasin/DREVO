$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path $PSScriptRoot -Parent
$LocalPath = Join-Path $ProjectRoot '.local'
if (Test-Path -LiteralPath $LocalPath) {
    $Identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
    & icacls.exe $LocalPath '/inheritance:r' '/grant:r' "${Identity}:(OI)(CI)F" 'SYSTEM:(OI)(CI)F' | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Не удалось ограничить доступ к .local.' }
}
$EnvPath = Join-Path $ProjectRoot '.env'
if (Test-Path -LiteralPath $EnvPath) {
    $Identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
    & icacls.exe $EnvPath '/inheritance:r' '/grant:r' "${Identity}:F" 'SYSTEM:F' | Out-Null
}
