# PostgreSQL 数据库

开发、测试、部署统一使用 PostgreSQL 16+ 和 psycopg 3。所有连接入口只接受 `postgresql://` 或 `postgres://`，没有 SQLite 驱动、文件数据库入口或回退路径。

## 本机已安装的实例

工程专用 PostgreSQL 16.15 位于 `backend/.postgresql/pgsql`，数据目录位于 `backend/.postgresql/data`，仅监听 `127.0.0.1:5432`。它不修改系统 PATH，也不注册 Windows 开机服务。数据库名和普通应用账号均为 `twinloop`；随机密码保存在忽略的本地配置，不写入文档。

Windows 下 PostgreSQL 子进程无法处理某些中文数据目录，管理脚本自动在用户临时目录创建英文路径 junction，实际文件仍保存在工程内。删除临时路径映射不会删除数据；管理脚本可重建它。

从仓库根目录运行：

```powershell
python backend/scripts/local_postgres.py status
python backend/scripts/local_postgres.py start
python backend/scripts/init_db.py
python backend/scripts/check_db.py
```

停止本机实例：

```powershell
python backend/scripts/local_postgres.py stop
```

换机器时，从 [EDB 官方 Windows 二进制页](https://www.enterprisedb.com/download-postgresql-binaries) 获取 PostgreSQL 16+ 的二进制压缩包，解压后应有 `backend/.postgresql/pgsql/bin/initdb.exe`，再运行：

```powershell
python -m pip install -e backend
python backend/scripts/local_postgres.py init
python backend/scripts/init_db.py
```

本次核验的下载包为 PostgreSQL 16.15-3 Windows x64，来源链接见官方页面。`local_postgres.py init` 重复执行不会清空数据或覆盖现有 `.env`。已有其他实例占用端口时可以首次初始化加 `--port 55432`。

## 配置和其他 PostgreSQL 实例

连接配置优先级：显式传入 URL > 环境变量 `DATABASE_URL` > `backend/.env`。没有配置时明确报错。连接超时 5 秒，不使用硬编码默认账号或密码。

本机初始化已生成 `backend/.env`。也可参考 `backend/.env.example` 配置远程 PostgreSQL；远程建议添加 `?sslmode=verify-full` 并配置 CA。不要在命令行输出真实连接串。

使用 Docker 的团队成员可配置本地 `.env` 后执行：

```powershell
docker compose --env-file backend/.env -f backend/docker-compose.yml up -d postgres
python backend/scripts/init_db.py
python backend/scripts/check_db.py
```

Docker 与本机实例择一启动，避免端口冲突；Compose 不覆盖本机账号和密码。生产环境通过密钥服务配置账号，迁移账号拥有 DDL 权限，运行账号应按需收紧到业务 DML 权限。

## 迁移规则

`schema.sql` 是 PostgreSQL 基线迁移 1，`migrations/002_personality_assessment.sql` 是迁移 2，`migrations/003_domain_selections.sql` 是迁移 3。当前 schema 版本为 3，领域选择表保存兴趣和自评熟悉度。

- JSON 数据用 `JSONB`，时间用 `TIMESTAMPTZ`，分享/跳过标志用 `BOOLEAN`。
- `initialize()` 在一个事务内持 PostgreSQL advisory lock，按序执行未应用迁移；失败时整体回滚。
- `schema_migrations` 保存版本、文件名、SHA-256 与应用时间。已应用文件内容变化或数据库版本高于应用时拒绝继续，不能静默覆盖。
- 新变更新增迁移文件，更新 `migration_files()`、`SCHEMA_VERSION`；不要编辑已发布迁移。
- 请求处理不自动建表。先运行初始化脚本，再启动 API。
- `with connect() as db` 成功时提交，异常时回滚，退出时关闭连接。

本次迁移时 `backend/data` 只有占位文件，没有待迁移的历史数据库或用户记录，所以执行的是 PostgreSQL 新库建表。没有清空或转换任何历史用户数据。旧原型 SQL 已替换，Git 历史只作为开发记录。

## 已接入的业务

性格测评写入、跳过、最新记录查询使用 PostgreSQL；中文 JSONB、原始答案、私有结果、幂等键和用户隔离均已验证。角色卡渲染读取该测评结果。

现有 FastAPI 的任务、画像草稿和发布版本仍是原有内存原型；这次不将未持久化的业务改造成新的数据库仓储。它们不是 SQLite 回退。原始知乎响应存储仍预留在 schema，尚未实现真实导入。

## 验证

测试只使用真实 PostgreSQL，并创建/删除随机 `test_twinloop_*` schema，不清空已有业务表。

```powershell
# 在已有 DATABASE_URL 的终端中
$env:TWINLOOP_TEST_DATABASE_URL = $env:DATABASE_URL
python -m unittest discover -s backend/tests -p "test_postgres.py" -v
```

需使用本机 `.env` 而没有环境变量时，在 Python 中把 `db.database.database_url()` 的值赋给测试变量后调用 unittest；不要打印 URL。未提供测试 URL 时数据库集成测试会明确跳过。

数据库目录、下载包、密码、本地 `.env`、Python 缓存不提交 Git。
