param([switch]$PlanOnly)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$runtimePython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
if (-not (Test-Path -LiteralPath $runtimePython)) { throw '找不到 Codex 文档运行时，请先加载 Workspace Dependencies。' }
Push-Location -LiteralPath $projectRoot
try {
    & $runtimePython scripts/build_image_bundle.py --plan
    if ($LASTEXITCODE -ne 0) { throw '图片任务清单生成失败' }
    if ($PlanOnly) { return }
    & '.\.venv\Scripts\python.exe' -m ops_rag.cli process --manifest data/image-task-manifest.json
    if ($LASTEXITCODE -ne 0) { throw '本地图片提取失败' }
    & $runtimePython scripts/build_image_bundle.py
    if ($LASTEXITCODE -ne 0) { throw '图文导入包生成失败' }
} finally { Pop-Location }
