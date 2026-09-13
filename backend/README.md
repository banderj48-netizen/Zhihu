# backend

存放数字分身平台后端，负责用户、数据导入、内容清洗、画像抽取、向量检索、Agent 编排和任务状态管理。

建议后续使用 Python + FastAPI。结构化数据使用 PostgreSQL，原始导入文件使用对象存储，耗时生成任务使用队列异步执行。

数据库统一使用 PostgreSQL，连接通过 `DATABASE_URL` 配置。SQLite 不支持，也不作为测试替代品；测试应使用独立 PostgreSQL 数据库或临时 schema。
