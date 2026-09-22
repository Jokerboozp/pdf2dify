$ErrorActionPreference = 'Stop'
$projectDir = $PSScriptRoot
$venvDir = Join-Path $projectDir '.venv'
if (-not (Test-Path -LiteralPath $venvDir)) {
    python -m venv $venvDir
}
$pythonExe = Join-Path $venvDir 'Scripts\python.exe'
& $pythonExe -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw 'pip 升级失败' }
& $pythonExe -m pip install -e "$projectDir[test]"
if ($LASTEXITCODE -ne 0) { throw 'Python 依赖安装失败' }
Push-Location (Join-Path $projectDir 'frontend')
try {
    npm install
    if ($LASTEXITCODE -ne 0) { throw '前端依赖安装失败' }
    npm run build
    if ($LASTEXITCODE -ne 0) { throw '前端构建失败' }
} finally {
    Pop-Location
}
Write-Host '安装完成。运行 .\start.ps1 启动 pdf2dify。'
