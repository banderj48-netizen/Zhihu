# 数据库初始化

首版本地数据库使用 SQLite，数据库文件默认位于 `backend/data/twinloop.db`。选择 SQLite 是因为当前开发机未安装 Docker 或 PostgreSQL，且 Python 自带 SQLite 驱动，不增加本地服务依赖。

表结构按后续 PostgreSQL 迁移设计，业务代码通过仓储层访问，不应直接依赖 SQLite 特有语法。

## 初始化

在仓库根目录执行：

```text
python backend/scripts/init_db.py
```

指定数据库路径：

```text
python backend/scripts/init_db.py --database backend/data/dev.db
```

重复执行是安全的。脚本使用 `schema.sql` 创建表和索引，并写入当前 schema 版本。

## 当前范围

数据库保存用户、分身、授权、初始化任务、知乎原始文档与证据、画像候选、审核事件、人格测评、三层记忆、版本、Agent 事件和删除审计。

原始知乎响应和完整引用保留在数据库是开发期方案；生产环境应迁移到对象存储，数据库只保存校验和、路径和元数据。
