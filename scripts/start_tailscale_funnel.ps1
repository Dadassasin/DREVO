$ErrorActionPreference = 'Stop'
$TailscaleCommand = Get-Command tailscale.exe -ErrorAction SilentlyContinue
if (-not $TailscaleCommand) { throw 'Установите Tailscale с tailscale.com/download и войдите в личную сеть.' }
$StatusJson = & $TailscaleCommand.Source status --json
if ($LASTEXITCODE -ne 0) { throw 'Не удалось получить состояние Tailscale.' }
$TailStatus = $StatusJson | ConvertFrom-Json
if ($TailStatus.BackendState -ne 'Running') { throw 'Сначала войдите в Tailscale и подключите этот компьютер.' }
Invoke-RestMethod 'http://127.0.0.1:8000/health' | Out-Null
& $TailscaleCommand.Source funnel --bg 'http://127.0.0.1:8000'
if ($LASTEXITCODE -ne 0) { throw 'Funnel не включён. Проверьте разрешение HTTPS/Funnel в Tailscale.' }
$FunnelHost = ([string]$TailStatus.Self.DNSName).TrimEnd('.')
Write-Host "Адрес API: https://$FunnelHost"
Write-Host 'Funnel сохраняется в службе Tailscale. Сервер ДРЕВО должен быть запущен.'
