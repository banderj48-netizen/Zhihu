# backend

存放数字分身平台后端，负责用户、数据导入、内容清洗、画像抽取、向量检索、Agent 编排和任务状态管理。

建议后续使用 Python + FastAPI。结构化数据使用 PostgreSQL，原始导入文件使用对象存储，耗时生成任务使用队列异步执行。

数据库统一使用 PostgreSQL，连接通过 `DATABASE_URL` 配置。SQLite 不支持，也不作为测试替代品；测试应使用独立 PostgreSQL 数据库或临时 schema。

## 启动后端

在项目根目录执行：

```powershell
.\backend\run_server.ps1
```

也可以手动启动：

```powershell
$env:PYTHONPATH="backend"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

`backend/app/main.py` 现在也提供了带中文说明的 `run_server()` 入口，因此可以在
项目根目录直接执行 `backend\\.venv\\Scripts\\python.exe backend/app/main.py`。
生产或需要热重载时，仍建议使用上面的 `run_server.ps1`，因为它会统一设置工作目录、
`PYTHONPATH` 和监听地址。Nginx 配置见 `infra/nginx.conf`。
