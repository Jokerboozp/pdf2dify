$ErrorActionPreference = 'Stop'
$runFile = Join-Path $PSScriptRoot 'data\run.json'
if (-not (Test-Path -LiteralPath $runFile)) {
    Write-Host '没有找到运行状态文件。'
    exit 0
}
$state = Get-Content -LiteralPath $runFile -Raw | ConvertFrom-Json
foreach ($processId in @($state.worker_pid, $state.api_pid)) {
    if ($processId -and (Get-Process -Id $processId -ErrorAction SilentlyContinue)) {
        Stop-Process -Id $processId
    }
}
Remove-Item -LiteralPath $runFile
Write-Host 'pdf2dify 已停止。'

