# PostgreSQL 数据库

开发、测试、部署统一使用 PostgreSQL 16+ 和 psycopg 3。所有连接入口只接受 `postgresql://` 或 `postgres://`，没有 SQLite 驱动、文件数据库入口或回退路径。

当前数字分身业务约束为：**一个用户只能有一个数字分身**。PostgreSQL 通过 `user_avatars.user_id` 的唯一约束在数据库层面保证该规则。

## 文件说明

| 文件 | 用途 |
|---|---|
| `schema.sql` | PostgreSQL 基线迁移表结构 |
| `database.py` | PostgreSQL 连接和迁移初始化逻辑 |
| `../scripts/init_db.py` | 初始化 PostgreSQL 数据库 |
| `postgresql_zhihu_schema.sql` | PostgreSQL 用户画像、原始资料、记忆、证据、版本和策略表 |
| `postgresql_chat_schema.sql` | PostgreSQL 聊天会话、参与者和真实消息表 |
| `postgresql_agent_dialogue.sql` | PostgreSQL 双 Agent 对话运行状态和评判结果表 |
| `postgresql_agent_presence.sql` | 场景在场状态和用户次日状态 |
| `postgresql_agent_chat_group_reads.sql` | 聊天组处理完成、可见时间和用户已读状态 |
| `migrations/` | SQLite 历史迁移脚本 |

## PostgreSQL 初始化

### 前置条件

1. 已安装并启动 PostgreSQL。
2. 已创建名为 `zhihu` 的数据库。
3. 执行账号有 `public` schema 的建表、建索引和创建扩展权限。

脚本会自动创建 `pgcrypto` 扩展，用于生成 UUID。如果后续需要使用 pgvector，可再单独安装该扩展并迁移向量字段；当前脚本不强制依赖 pgvector。

### 执行顺序

必须先执行用户画像基础脚本，再执行聊天记录脚本：

```powershell
psql -U postgres -d zhihu -f E:\ZH\Zhihu\backend\db\postgresql_zhihu_schema.sql
psql -U postgres -d zhihu -f E:\ZH\Zhihu\backend\db\postgresql_chat_schema.sql
psql -U postgres -d zhihu -f E:\ZH\Zhihu\backend\db\postgresql_agent_dialogue.sql
psql -U postgres -d zhihu -f E:\ZH\Zhihu\backend\db\postgresql_agent_chat_groups.sql
psql -U postgres -d zhihu -f E:\ZH\Zhihu\backend\db\postgresql_agent_presence.sql
psql -U postgres -d zhihu -f E:\ZH\Zhihu\backend\db\postgresql_agent_chat_group_reads.sql
```

也可以在 pgAdmin 中打开 `zhihu` 数据库的 Query Tool，依次打开并执行两个 SQL 文件。

两个脚本都使用 `CREATE TABLE IF NOT EXISTS` 和 `CREATE INDEX IF NOT EXISTS`，可以重复执行。重复执行不会清空已有数据。

## 用户画像表关系

```text
users
 └── user_avatars              唯一数字分身（一对一）
      ├── avatar_versions      画像历史版本
      │    ├── avatar_identity
      │    ├── avatar_personality
      │    └── avatar_styles
      ├── avatar_memories       事实、经历、专长、兴趣、观点和行为
      │    └── memory_evidence  记忆对应的原文证据
      ├── source_documents      知乎原始回答、文章和评论
      ├── avatar_style_examples 真实表达样例
      ├── avatar_memory_rules   记忆检索规则
      ├── avatar_policies       安全和隐私策略
      ├── avatar_growth_evaluations 成长评估
      └── avatar_change_logs    修改审计
```

核心设计说明：

- `user_avatars.user_id` 唯一，保证一个用户最多一条数字分身记录。
- `avatar_versions` 允许同一个数字分身保留多个历史版本，但同一时间只能有一个 `active` 版本。
- 画像记忆和性格推断都保存 `confidence`、`status`、`privacy` 等控制字段。
- `memory_evidence` 将模型结论关联回原始资料，支持引用和追溯。
- `avatar_policies` 控制是否可以使用未确认记忆、是否必须展示不确定性等行为边界。

## 聊天记录表关系

```text
chat_conversations
 └── chat_participants       会话参与者
      └── chat_messages      真实聊天消息
```

### `chat_conversations`

保存一次聊天的整体信息，包括会话 ID、类型、标题、状态、开始时间、结束时间和扩展元数据。

### `chat_participants`

保存参与会话的数字分身或系统参与者。`display_name` 是名称快照，确保数字分身改名后历史记录仍能正确展示。

### `chat_messages`

保存每一条真实消息，关键字段包括：

- `id`：消息 UUID。
- `conversation_id`：所属会话。
- `participant_id`：发送者。
- `sequence_no`：会话内递增序号，用于稳定排序。
- `client_message_id`：客户端或上游消息 ID，用于幂等去重。
- `content`：消息原文或 JSON 内容。
- `message_type`：文本、图片、文件、音频、视频、事件或系统消息。
- `sent_at`：消息实际发送时间。
- `created_at`：消息写入数据库时间。
- `edited_at`、`deleted_at`：编辑和软删除时间。
- `metadata`：模型版本、请求 ID、token 统计等扩展信息。

消息表使用复合外键 `(participant_id, conversation_id)`，保证发送者确实属于当前会话。消息删除默认采用软删除，查询普通历史时应增加 `deleted_at IS NULL` 条件。

## 常用聊天操作

### 创建会话并添加两个分身

```sql
INSERT INTO public.chat_conversations (title)
VALUES ('数字分身对话')
RETURNING id;

INSERT INTO public.chat_participants (conversation_id, avatar_id, display_name)
VALUES
    ('会话UUID', '分身UUID_A', '分身A'),
    ('会话UUID', '分身UUID_B', '分身B');
```

### 写入一条消息

`sequence_no` 应由应用在事务中按会话递增生成；同一会话不能重复使用同一个序号。

```sql
INSERT INTO public.chat_messages (
    conversation_id, participant_id, sequence_no,
    client_message_id, message_type, content, sent_at
)
VALUES (
    '会话UUID', '参与者UUID', 1,
    '上游消息ID', 'text', '这是消息原文', now()
)
ON CONFLICT (conversation_id, client_message_id) DO NOTHING;
```

### 按顺序读取聊天记录

```sql
SELECT m.id, m.sequence_no, p.avatar_id, p.display_name,
       m.message_type, m.content, m.sent_at
FROM public.chat_messages AS m
JOIN public.chat_participants AS p ON p.id = m.participant_id
WHERE m.conversation_id = '会话UUID'
  AND m.deleted_at IS NULL
ORDER BY m.sequence_no ASC;
```

### 查询某个分身参与过的会话

```sql
SELECT DISTINCT c.*
FROM public.chat_conversations AS c
JOIN public.chat_participants AS p ON p.conversation_id = c.id
WHERE p.avatar_id = '分身UUID'
ORDER BY c.updated_at DESC;
```

## SQLite 本地开发
## 本机已安装的实例

工程专用 PostgreSQL 16.15 位于 `backend/.postgresql/pgsql`，数据目录位于 `backend/.postgresql/data`，仅监听 `127.0.0.1:5432`。它不修改系统 PATH，也不注册 Windows 开机服务。数据库名和普通应用账号均为 `twinloop`；随机密码保存在忽略的本地配置，不写入文档。
Windows 下 PostgreSQL 子进程无法处理某些中文数据目录，管理脚本自动在用户临时目录创建英文路径 junction，实际文件仍保存在工程内。删除临时路径映射不会删除数据；管理脚本可重建它。

## 数据安全和维护注意事项

- 原始知乎内容和聊天消息可能包含个人隐私，生产环境应限制数据库账号权限并做好备份加密。
- 不要把密码、访问令牌或第三方 OAuth token 直接写入 `content` 或普通 `metadata` 字段。
- 画像推断结果不能默认当作用户事实；读取时应检查 `status` 和 `confidence`。
- 业务代码更新会话的 `updated_at`，写入消息时应在同一事务中更新会话时间。
- 删除用户时，画像和聊天记录会按外键级联删除；执行前应确认这符合数据保留政策。
- 新增数据库表或字段后，应同步补充本 README 和根目录 `AGENTS.md` 中的说明。

## 本地 PostgreSQL 操作

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
## 数字分身初始化与反馈

执行 `postgresql_twin_initialization.sql`（需先执行 `postgresql_agent_dialogue.sql`），创建初始化会话、心灵感应反馈和性格调整累计表。初始化流程通过 `backend/agent/runtime/api.py` 暴露，PostgreSQL 保存事实数据，Chroma 仍由既有同步队列负责。
聊天组索引使用 `postgresql_agent_chat_groups.sql`，应在 `postgresql_agent_dialogue.sql` 之后执行。它只保存一次双 Agent 运行的发起方、被邀请方、`chat_no` 和状态；正文仍从 `chat_messages` 查询。

查询接口：`GET /v1/twin/chat-groups/count` 统计用户参与的组数，`GET /v1/twin/chat-groups` 分页列出双方，`GET /v1/twin/chat-groups/{chat_no}/messages` 查询完整消息。接口会校验用户是否为发起方或被邀请方。
