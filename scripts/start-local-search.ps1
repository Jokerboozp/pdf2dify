param([int]$Port = 8765, [string]$BindAddress = '192.168.24.1')
$ErrorActionPreference = 'Stop'
$projectDir = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$pythonExe = Join-Path $projectDir '.venv\Scripts\python.exe'
$logDir = Join-Path $projectDir 'logs'
New-Item -ItemType Directory -Path $logDir -Force | Out-Null
if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
    Write-Host "Port $Port is already listening. Verify /health before starting another instance."
    exit 1
}
$process = Start-Process -FilePath $pythonExe -ArgumentList @('-m', 'ops_rag.cli', 'serve', '--host', $BindAddress, '--port', $Port) -WorkingDirectory $projectDir -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logDir 'local-search.stdout.log') -RedirectStandardError (Join-Path $logDir 'local-search.stderr.log')
$process.Id | Set-Content -LiteralPath (Join-Path $logDir 'local-search-launcher.pid')
Write-Host "Starting local search: http://${BindAddress}:$Port/health; launcher PID $($process.Id)."
