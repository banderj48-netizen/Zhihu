param(
    [Parameter(Mandatory = $true)]
    [string]$BackupFile,
    [string]$DatabaseUrl = "",
    [switch]$Force
)

$ErrorActionPreference = 'Stop'

<#
用途：将 pg_dump 数据备份恢复到已存在的 PostgreSQL 表中。
说明：本脚本只恢复表数据和序列值，不删除或创建表；默认要求显式传入 -Force。
#>
function Read-DatabaseUrl {
    param([string]$ConfiguredUrl)
    if (-not [string]::IsNullOrWhiteSpace($ConfiguredUrl)) { return $ConfiguredUrl }
    $envPath = Join-Path $PSScriptRoot '..\.env'
    if (-not (Test-Path -LiteralPath $envPath)) { throw "未找到 backend/.env，请使用 -DatabaseUrl 指定连接串。" }
    $line = Get-Content -LiteralPath $envPath -Encoding UTF8 | Where-Object { $_ -match '^DATABASE_URL=' } | Select-Object -First 1
    if (-not $line) { throw "backend/.env 中未配置 DATABASE_URL。" }
    return ($line -replace '^DATABASE_URL=', '').Trim()
}

<# 解析连接串并设置本次进程使用的密码环境变量。 #>
function Get-ConnectionParts {
    param([string]$Url)
    $uri = [Uri]$Url
    $parts = $uri.UserInfo -split ':', 2
    if ($parts.Count -lt 2) { throw 'DATABASE_URL 缺少用户名或密码。' }
    return [pscustomobject]@{
        Host = $uri.Host
        Port = if ($uri.Port -gt 0) { $uri.Port } else { 5432 }
        User = $parts[0]
        Password = [Uri]::UnescapeDataString($parts[1])
        Database = $uri.AbsolutePath.TrimStart('/')
    }
}

if (-not (Test-Path -LiteralPath $BackupFile)) { throw "备份文件不存在：$BackupFile" }
if (-not $Force) {
    throw '恢复会覆盖现有表数据。确认后请重新运行并追加 -Force。'
}

$pgRestore = (Get-Command pg_restore -ErrorAction SilentlyContinue).Source
if (-not $pgRestore) { $pgRestore = 'E:\Postgres\bin\pg_restore.exe' }
if (-not (Test-Path -LiteralPath $pgRestore)) { throw "未找到 pg_restore：$pgRestore" }

$parts = Get-ConnectionParts (Read-DatabaseUrl $DatabaseUrl)
$env:PGPASSWORD = $parts.Password
try {
    & $pgRestore --data-only --disable-triggers --exit-on-error --no-owner --no-privileges `
        --host $parts.Host --port $parts.Port --username $parts.User --dbname $parts.Database $BackupFile
    if ($LASTEXITCODE -ne 0) { throw "pg_restore 失败，退出码：$LASTEXITCODE" }
    Write-Output "数据库恢复完成：$($parts.Database)"
}
finally {
    Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
}
