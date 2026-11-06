param(
    [string]$ArchiveRoot = 'F:\Архив',
    [string]$InstallDirectory = (Join-Path $env:LOCALAPPDATA 'DREVO'),
    [switch]$CheckOnly
)
$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$Portable = Join-Path $ArchiveRoot '.drevo'
foreach ($Name in @('drevo.sqlite3', 'signing.key', 'server.env', 'app-source.zip', 'app-source.sha256')) {
    if (-not (Test-Path -LiteralPath (Join-Path $Portable $Name) -PathType Leaf)) { throw "Не найден $Portable\$Name. Подключите подготовленный диск F:." }
}
if ($ArchiveRoot -ne 'F:\Архив') { throw 'Этот перенос подготовлен для F:\Архив. Назначьте диску букву F:.' }
$ExpectedHash = (Get-Content -LiteralPath (Join-Path $Portable 'app-source.sha256') -Raw).Trim()
if ((Get-FileHash -LiteralPath (Join-Path $Portable 'app-source.zip') -Algorithm SHA256).Hash -ne $ExpectedHash) { throw 'Установочный архив повреждён. Не продолжайте установку; обновите комплект с первого ПК.' }
if ($CheckOnly) {
    Write-Output "Архив и установочный комплект найдены. Каталог установки: $InstallDirectory"
    foreach ($Name in @('py.exe', 'node.exe', 'winget.exe')) { Write-Output "$Name : $([bool](Get-Command $Name -ErrorAction SilentlyContinue))" }
    return
}
function Refresh-CommandPath {
    $env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User') + ';' + $env:Path
}
function Install-Dependency([string]$Package) {
    if (-not (Get-Command winget.exe -ErrorAction SilentlyContinue)) { throw 'Нужен Microsoft App Installer (winget). Установите из Microsoft Store: https://apps.microsoft.com/detail/9nblggh4nns1 и повторите запуск.' }
    Write-Host "Устанавливаю $Package. Windows может запросить разрешение администратора."
    & winget.exe install --id $Package --exact --source winget --accept-package-agreements --accept-source-agreements --silent --no-upgrade
    if ($LASTEXITCODE -ne 0) { throw "Установка $Package не завершена. Если нужна перезагрузка, выполните её и запустите установщик снова." }
    Refresh-CommandPath
}
$PythonOK = $false
if (Get-Command py.exe -ErrorAction SilentlyContinue) {
    $PythonOK = (& py.exe -3.12 -c 'import sys; print(sys.version_info >= (3,12))') -eq 'True'
}
if (-not $PythonOK) { Install-Dependency 'Python.Python.3.12' }
$NodeOK = $false
if (Get-Command node.exe -ErrorAction SilentlyContinue) {
    $NodeOK = (& node.exe -p '((v)=>v[0]>22||(v[0]===22&&v[1]>=12))(process.versions.node.split(String.fromCharCode(46)).map(Number))') -eq 'true'
}
if (-not $NodeOK) { Install-Dependency 'OpenJS.NodeJS.LTS' }
$TailscalePath = Join-Path $env:ProgramFiles 'Tailscale/tailscale.exe'
if (-not (Test-Path -LiteralPath $TailscalePath)) { Install-Dependency 'Tailscale.Tailscale' }
Refresh-CommandPath
if (-not (Get-Command py.exe -ErrorAction SilentlyContinue) -or -not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) { throw 'Команды Python/Node ещё недоступны. Закройте это окно и повторите установку.' }
if (Test-Path -LiteralPath $InstallDirectory) {
    if (-not (Test-Path -LiteralPath (Join-Path $InstallDirectory '.drevo-installed.json'))) { throw "Каталог $InstallDirectory уже существует и не принадлежит этому установщику. Выберите другой InstallDirectory." }
    $StopScript = Join-Path $InstallDirectory 'scripts/stop_all.ps1'
    if (Test-Path -LiteralPath $StopScript) {
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $StopScript
        if ($LASTEXITCODE -ne 0) { throw 'Сначала завершите работу установленного сервера.' }
    }
} else { New-Item -ItemType Directory -Path $InstallDirectory | Out-Null }
@{ application='DREVO'; archive=$ArchiveRoot } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $InstallDirectory '.drevo-installed.json') -Encoding UTF8
# Bundle contains program files only. An existing machine's private .env is preserved.
Expand-Archive -LiteralPath (Join-Path $Portable 'app-source.zip') -DestinationPath $InstallDirectory -Force
$EnvFile = Join-Path $InstallDirectory '.env'
if (-not (Test-Path -LiteralPath $EnvFile)) { Copy-Item -LiteralPath (Join-Path $Portable 'server.env') -Destination $EnvFile }
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $InstallDirectory 'scripts/setup_windows.ps1') -PythonVersion '3.12'
if ($LASTEXITCODE -ne 0) { throw 'Установка ДРЕВО не завершена. Запустите установщик повторно после устранения ошибки.' }
$Shell = New-Object -ComObject WScript.Shell
$Desktop = [Environment]::GetFolderPath('Desktop')
foreach ($Item in @(@('ДРЕВО — запустить сайт', 'start_online.bat'), @('ДРЕВО — остановить сервер', 'stop_server.bat'))) {
    $Shortcut = $Shell.CreateShortcut((Join-Path $Desktop ($Item[0] + '.lnk')))
    $Shortcut.TargetPath = Join-Path $InstallDirectory $Item[1]
    $Shortcut.WorkingDirectory = $InstallDirectory
    $Shortcut.Save()
}
Write-Host 'Установка готова. Сейчас потребуется подтвердить вход в Tailscale/Funnel и Vercel. Пароли в скрипт не сохраняются.'
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $InstallDirectory 'scripts/start_online.ps1')
if ($LASTEXITCODE -ne 0) { throw 'Локальная установка готова, но онлайн-подключение не завершено. Повторите ярлык «ДРЕВО — запустить сайт».' }
Write-Host 'Готово: https://drevo-beta.vercel.app. Для последующих запусков используйте ярлык на рабочем столе.'
