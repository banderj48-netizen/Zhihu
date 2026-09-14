param(
    [string]$DatabaseUrl = "",
    [switch]$Force
)

$ErrorActionPreference = 'Stop'

<#
用途：清空用户创建 schema 中所有表的数据，但保留表、字段、约束、索引和函数。
安全：必须显式传入 -Force；脚本不会执行 DROP TABLE 或 DROP SCHEMA。
#>
function Read-DatabaseUrl {
    param([string]$ConfiguredUrl)
    if (-not [string]::IsNullOrWhiteSpace($ConfiguredUrl)) { return $ConfiguredUrl }
    $envPath = Join-Path $PSScriptRoot '..\.env'
    $line = Get-Content -LiteralPath $envPath -Encoding UTF8 | Where-Object { $_ -match '^DATABASE_URL=' } | Select-Object -First 1
    if (-not $line) { throw '未找到 DATABASE_URL。' }
    return ($line -replace '^DATABASE_URL=', '').Trim()
}

if (-not $Force) { throw '清空操作不可逆。确认后请重新运行并追加 -Force。' }
$psql = (Get-Command psql -ErrorAction SilentlyContinue).Source
if (-not $psql) { $psql = 'E:\Postgres\bin\psql.exe' }
if (-not (Test-Path -LiteralPath $psql)) { throw "未找到 psql：$psql" }

$uri = [Uri](Read-DatabaseUrl $DatabaseUrl)
$parts = $uri.UserInfo -split ':', 2
if ($parts.Count -lt 2) { throw 'DATABASE_URL 缺少用户名或密码。' }
$env:PGPASSWORD = [Uri]::UnescapeDataString($parts[1])
$port = if ($uri.Port -gt 0) { $uri.Port } else { 5432 }
$sql = @"
DO `$`$
DECLARE
    item record;
BEGIN
    -- Truncate user tables only; CASCADE handles foreign keys without dropping objects.
    FOR item IN
        SELECT format('%I.%I', schemaname, tablename) AS table_name
        FROM pg_catalog.pg_tables
        WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
    LOOP
        EXECUTE 'TRUNCATE TABLE ' || item.table_name || ' RESTART IDENTITY CASCADE';
    END LOOP;
END
`$`$;
"@
try {
    & $psql --host $uri.Host --port $port --username $parts[0] --dbname $uri.AbsolutePath.TrimStart('/') --command $sql
    if ($LASTEXITCODE -ne 0) { throw "清空失败，退出码：$LASTEXITCODE" }
    Write-Output '用户创建 schema 的表数据已清空，表结构已保留。'
}
finally {
    Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
}
