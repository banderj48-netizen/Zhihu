# 使用 Uvicorn 启动 FastAPI，避免从错误工作目录运行导致 app 包无法导入。
$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    $python = Join-Path $projectRoot ".venv\Scripts\python.exe"
}
if (-not (Test-Path -LiteralPath $python)) { throw "未找到虚拟环境解释器，请先安装 backend/pyproject.toml 中的依赖。" }

Set-Location -LiteralPath $projectRoot
$env:PYTHONPATH = "backend"
& $python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
