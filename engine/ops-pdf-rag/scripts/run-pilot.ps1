param([switch]$SkipOcr)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location -LiteralPath $projectRoot
try {
    $pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $pythonPath)) { throw '先运行 scripts\setup.ps1' }
    $commands = @(@('scan'), @('plan'), @('native'))
    if (-not $SkipOcr) { $commands += ,@('process') }
    $commands += @(@('cards'), @('procedures'), @('export','--include-drafts'), @('report'), @('evaluate'))
    foreach ($arguments in $commands) {
        & $pythonPath -m ops_rag.cli @arguments
        if ($LASTEXITCODE -ne 0) { throw ('失败：' + ($arguments -join ' ')) }
    }
} finally { Pop-Location }
