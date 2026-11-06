$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path $PSScriptRoot -Parent
& "$PSScriptRoot/start_all.ps1"
$Ready = $false
for ($Attempt = 0; $Attempt -lt 30; $Attempt++) {
    try {
        $Health = Invoke-RestMethod 'http://127.0.0.1:8000/health' -TimeoutSec 3
        if ($Health.status -eq 'ok') { $Ready = $true; break }
    } catch { }
    Start-Sleep -Seconds 1
}
if (-not $Ready) { throw 'Локальный сервер не ответил. См. .local/server-error.log.' }
$TailscaleExe = (Get-Command tailscale.exe -ErrorAction SilentlyContinue).Source
if (-not $TailscaleExe) { $TailscaleExe = Join-Path $env:ProgramFiles 'Tailscale/tailscale.exe' }
if (-not (Test-Path -LiteralPath $TailscaleExe)) { throw 'Запустите установщик второго ПК: Tailscale не установлен.' }
$StateJson = & $TailscaleExe status --json
$TailState = $StateJson | ConvertFrom-Json
if ($TailState.BackendState -ne 'Running') {
    $NodeName = ('drevo-' + $env:COMPUTERNAME.ToLower()) -replace '[^a-z0-9-]', '-'
    Write-Host 'Подтвердите вход в Tailscale по показанной ссылке.'
    & $TailscaleExe login --hostname=$NodeName --accept-dns=false --accept-routes=false
    if ($LASTEXITCODE -ne 0) { throw 'Вход в Tailscale не завершён.' }
}
Write-Host 'Включаю Funnel. При первом запуске подтвердите разрешение по ссылке Tailscale.'
& $TailscaleExe funnel --bg 'http://127.0.0.1:8000'
if ($LASTEXITCODE -ne 0) { throw 'Funnel не включён. Повторите после подтверждения в Tailscale.' }
$TailState = (& $TailscaleExe status --json) | ConvertFrom-Json
$FunnelHost = ([string]$TailState.Self.DNSName).TrimEnd('.')
if (-not $FunnelHost) { throw 'Tailscale не сообщил HTTPS-имя устройства.' }
Push-Location $ProjectRoot
try {
    & "$ProjectRoot/.venv/Scripts/python.exe" -X utf8 "$PSScriptRoot/switch_online.py" "https://$FunnelHost"
    if ($LASTEXITCODE -ne 0) { throw 'Сайт не переключён. Локальный адрес: http://127.0.0.1:8000. Повторите start_online.bat.' }
} finally { Pop-Location }
