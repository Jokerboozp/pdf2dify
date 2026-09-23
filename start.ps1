param(
    [switch]$Dev
)

$ErrorActionPreference = 'Stop'
$projectDir = $PSScriptRoot
$pythonExe = Join-Path $projectDir '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonExe)) {
    throw '虚拟环境不存在，请先运行 .\setup.ps1'
}
if (-not (Test-Path -LiteralPath (Join-Path $projectDir 'frontend\dist\index.html'))) {
    throw '前端尚未构建，请先运行 .\setup.ps1'
}
$enginePython = if ($env:PDF2DIFY_ENGINE_PYTHON) { $env:PDF2DIFY_ENGINE_PYTHON } else { Join-Path $projectDir 'engine\ops-pdf-rag\.venv\Scripts\python.exe' }
if (-not (Test-Path -LiteralPath $enginePython)) {
    throw '解析引擎环境不存在，请先运行 .\setup.ps1'
}
$runFile = Join-Path $projectDir 'data\run.json'
if (Test-Path -LiteralPath $runFile) {
    $oldRun = Get-Content -LiteralPath $runFile -Raw | ConvertFrom-Json
    $oldWorker = Get-Process -Id $oldRun.worker_pid -ErrorAction SilentlyContinue
    $oldApi = Get-Process -Id $oldRun.api_pid -ErrorAction SilentlyContinue
    if ($oldWorker -and (-not $oldRun.worker_started -or $oldWorker.StartTime.ToUniversalTime().Ticks -ne ([datetime]$oldRun.worker_started).ToUniversalTime().Ticks)) { $oldWorker = $null }
    if ($oldApi -and (-not $oldRun.api_started -or $oldApi.StartTime.ToUniversalTime().Ticks -ne ([datetime]$oldRun.api_started).ToUniversalTime().Ticks)) { $oldApi = $null }
    if ($oldWorker -and $oldApi) {
        Write-Host 'pdf2dify 已在运行：http://127.0.0.1:8010'
        Start-Process 'http://127.0.0.1:8010'
        exit 0
    }
    if ($oldWorker -or $oldApi) {
        throw '检测到上次启动的部分进程仍在运行，请先运行 .\stop.ps1'
    }
    Remove-Item -LiteralPath $runFile
}
$existingApi = $null
try { $existingApi = Invoke-RestMethod -Uri 'http://127.0.0.1:8010/api/health' -TimeoutSec 1 } catch { }
if ($existingApi -and $existingApi.status -eq 'ok') {
    throw '8010 端口已有未登记的 pdf2dify 服务，请先停止该进程'
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

@{ worker_pid = $worker.Id; api_pid = $api.Id; worker_started = $worker.StartTime.ToUniversalTime().ToString('o'); api_started = $api.StartTime.ToUniversalTime().ToString('o') } | ConvertTo-Json | Set-Content -LiteralPath $runFile -Encoding UTF8
$ready = $false
for ($attempt = 0; $attempt -lt 20; $attempt++) {
    Start-Sleep -Milliseconds 500
    try {
        $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8010/api/health' -TimeoutSec 2
        if ($health.status -eq 'ok' -and $health.engine_ready -and (Get-Process -Id $worker.Id -ErrorAction SilentlyContinue)) { $ready = $true; break }
    } catch { }
    if (-not (Get-Process -Id $api.Id -ErrorAction SilentlyContinue)) { break }
}
if (-not $ready) {
    foreach ($startedId in @($worker.Id, $api.Id)) {
        if (Get-Process -Id $startedId -ErrorAction SilentlyContinue) {
            & taskkill.exe /PID $startedId /T /F | Out-Null
        }
    }
    Remove-Item -LiteralPath $runFile
    throw 'pdf2dify API 未能启动，请查看 data\logs\api.stderr.log'
}
Start-Process 'http://127.0.0.1:8010'
Write-Host "pdf2dify 已启动：http://127.0.0.1:8010"
Write-Host "Worker PID=$($worker.Id)，API PID=$($api.Id)"
