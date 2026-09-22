$ErrorActionPreference = 'Stop'
$projectDir = $PSScriptRoot
$venvDir = Join-Path $projectDir '.venv'
if (-not (Test-Path -LiteralPath $venvDir)) {
    python -m venv $venvDir
}
$pythonExe = Join-Path $venvDir 'Scripts\python.exe'
$engineDir = Join-Path $projectDir 'engine\ops-pdf-rag'
$enginePython = Join-Path $engineDir '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath (Join-Path $engineDir 'pyproject.toml'))) {
    throw '缺少内置解析引擎，请重新克隆完整仓库'
}
& $pythonExe -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw 'pip 升级失败' }
& $pythonExe -m pip install -e "$projectDir[test]"
if ($LASTEXITCODE -ne 0) { throw 'Python 依赖安装失败' }
if (-not (Test-Path -LiteralPath $enginePython)) {
    python -m venv (Join-Path $engineDir '.venv')
    if ($LASTEXITCODE -ne 0) { throw '解析引擎环境创建失败' }
}
& $enginePython -m pip install -r (Join-Path $engineDir 'requirements.lock.txt')
if ($LASTEXITCODE -ne 0) { throw '解析引擎依赖安装失败' }
& $enginePython -m pip install --no-deps -e $engineDir
if ($LASTEXITCODE -ne 0) { throw '解析引擎安装失败' }
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
