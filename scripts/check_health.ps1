$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path $PSScriptRoot -Parent
Invoke-RestMethod 'http://127.0.0.1:8000/api/v1/health'
Push-Location (Join-Path $ProjectRoot 'backend')
try { & '../.venv/Scripts/python.exe' -X utf8 -m app.cli check } finally { Pop-Location }
$TailscaleExe = Join-Path $env:ProgramFiles 'Tailscale/tailscale.exe'
if (Test-Path -LiteralPath $TailscaleExe) {
    $TailState = (& $TailscaleExe status --json) | ConvertFrom-Json
    Write-Host "Tailscale: $($TailState.BackendState); Online: $($TailState.Self.Online); Funnel: $($TailState.Self.DNSName)"
}
