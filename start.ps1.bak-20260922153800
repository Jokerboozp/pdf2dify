param(
    [switch]$Dev
)

$ErrorActionPreference = 'Stop'
$projectDir = $PSScriptRoot
$pythonExe = Join-Path $projectDir '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonExe)) {
    throw '虚拟环境不存在，请先运行 .\setup.ps1'
}
$logDir = Join-Path $projectDir 'data\logs'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

$worker = Start-Process -FilePath $pythonExe -ArgumentList @('-m','pdf2dify.worker') `
    -WorkingDirectory $projectDir -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput (Join-Path $logDir 'worker.stdout.log') `
    -RedirectStandardError (Join-Path $logDir 'worker.stderr.log')
$api = Start-Process -FilePath $pythonExe -ArgumentList @('-m','pdf2dify.main') `
    -WorkingDirectory $projectDir -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput (Join-Path $logDir 'api.stdout.log') `
    -RedirectStandardError (Join-Path $logDir 'api.stderr.log')

@{ worker_pid = $worker.Id; api_pid = $api.Id } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $projectDir 'data\run.json') -Encoding UTF8
Start-Sleep -Seconds 2
Start-Process 'http://127.0.0.1:8010'
Write-Host "pdf2dify 已启动：http://127.0.0.1:8010"
Write-Host "Worker PID=$($worker.Id)，API PID=$($api.Id)"

