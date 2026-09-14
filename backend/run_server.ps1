param([ValidateSet('local','server')][string]$Environment='local')
$ErrorActionPreference='Stop'
$backendRoot=Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot=Split-Path -Parent $backendRoot
$python=Join-Path $backendRoot '.venv\Scripts\python.exe'
if(-not(Test-Path -LiteralPath $python)){$python=(Get-Command python -ErrorAction SilentlyContinue).Source}
if([string]::IsNullOrWhiteSpace($python)){throw 'Python was not found.'}
$envFileName='.env.local';$bindAddress='127.0.0.1'
if($Environment -eq 'server'){$envFileName='.env';$bindAddress='0.0.0.0'}
$env:TWINLOOP_ENV_FILE=Join-Path $backendRoot $envFileName
$env:TWINLOOP_MODEL_ENV_FILE=Join-Path $backendRoot '.env.models'
if(-not(Test-Path -LiteralPath $env:TWINLOOP_ENV_FILE)){throw ('Environment file not found: '+$env:TWINLOOP_ENV_FILE)}
Set-Location -LiteralPath $repoRoot
$env:PYTHONPATH='backend'
& $python -m uvicorn app.main:app --app-dir backend --host $bindAddress --port 8000
