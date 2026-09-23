$ErrorActionPreference = 'Stop'
$runFile = Join-Path $PSScriptRoot 'data\run.json'
if (-not (Test-Path -LiteralPath $runFile)) {
    Write-Host '没有找到运行状态文件。'
    exit 0
}
$state = Get-Content -LiteralPath $runFile -Raw | ConvertFrom-Json
foreach ($entry in @(@($state.worker_pid, $state.worker_started), @($state.api_pid, $state.api_started))) {
    $processId = $entry[0]
    $expectedStart = $entry[1]
    $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
    if ($process -and $expectedStart -and $process.StartTime.ToUniversalTime().Ticks -eq ([datetime]$expectedStart).ToUniversalTime().Ticks) {
        & taskkill.exe /PID $processId /T /F | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "无法停止任务进程树：$processId" }
    }
}
Remove-Item -LiteralPath $runFile
Write-Host 'pdf2dify 已停止。'
