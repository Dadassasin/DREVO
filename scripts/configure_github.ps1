$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path $PSScriptRoot -Parent
Write-Host 'Создайте fine-grained токен только для Dadassasin/DREVO-Research-Data: Contents — Read and write, Metadata — Read.'
Write-Host 'https://github.com/settings/personal-access-tokens/new?name=DREVO-sync&target_name=Dadassasin&expires_in=30&contents=write'
Write-Host 'Токен вводится здесь скрыто. В чат его отправлять не нужно.'
$Secret = Read-Host 'GitHub fine-grained token' -AsSecureString
$Pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Secret)
try {
    $Token = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($Pointer)
    if ($Token -notmatch '^github_pat_[A-Za-z0-9_]+$') { throw 'Нужен fine-grained токен github_pat_…' }
    $Headers = @{ Authorization="Bearer $Token"; Accept='application/vnd.github+json'; 'X-GitHub-Api-Version'='2022-11-28' }
    try { $Repo = Invoke-RestMethod 'https://api.github.com/repos/Dadassasin/DREVO-Research-Data' -Headers $Headers } catch { throw 'GitHub не подтвердил доступ к репозиторию. Проверьте выбранный репозиторий и права токена.' }
    if (-not $Repo.private) { throw 'Синхронизация разрешена только с приватным репозиторием.' }
    $EnvFile = Join-Path $ProjectRoot '.env'
    $Text = [IO.File]::ReadAllText($EnvFile)
    if ($Text -match '(?m)^DREVO_GITHUB_TOKEN=') { $Text = [regex]::Replace($Text, '(?m)^DREVO_GITHUB_TOKEN=.*$', "DREVO_GITHUB_TOKEN=$Token") }
    else { $Text += "`nDREVO_GITHUB_TOKEN=$Token`n" }
    [IO.File]::WriteAllText($EnvFile, $Text, (New-Object Text.UTF8Encoding($false)))
    Write-Host 'Доступ проверен. Токен сохранён только в .env на этом ПК. Рабочий сервер не перезапускался.'
} finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($Pointer)
    $Token = $null
    $Headers = $null
}
