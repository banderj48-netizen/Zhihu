# 使用 Uvicorn 启动 FastAPI，避免从错误工作目录运行导致 app 包无法导入。
param([ValidateSet("local", "server")][string]$Environment = "local")
$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    $python = Join-Path $projectRoot ".venv\Scripts\python.exe"
}
if (-not (Test-Path -LiteralPath $python)) { throw "未找到虚拟环境解释器，请先安装 backend/pyproject.toml 中的依赖。" }

Set-Location -LiteralPath $projectRoot
$env:PYTHONPATH = "backend"
$envName = ".env.local"
if ($Environment -eq "server") { $envName = ".env" }
$env:TWINLOOP_ENV_FILE = Join-Path $PSScriptRoot $envName
if (-not (Test-Path -LiteralPath $env:TWINLOOP_ENV_FILE)) { throw ("未找到环境文件: " + $env:TWINLOOP_ENV_FILE) }
$bindAddress = "127.0.0.1"
if ($Environment -eq "server") { $bindAddress = "0.0.0.0" }
& $python -m uvicorn app.main:app --app-dir backend --host $bindAddress --port 8000
