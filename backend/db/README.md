# 数据库说明

本目录同时维护项目当前的 SQLite 本地开发结构和 PostgreSQL 生产/集成结构。

当前数字分身业务约束为：**一个用户只能有一个数字分身**。PostgreSQL 通过 `user_avatars.user_id` 的唯一约束在数据库层面保证该规则。

## 文件说明

| 文件 | 用途 |
|---|---|
| `schema.sql` | SQLite 本地开发表结构，供 Python 初始化脚本使用 |
| `database.py` | SQLite 连接和初始化逻辑 |
| `../scripts/init_db.py` | 初始化本地 SQLite 数据库 |
| `postgresql_zhihu_schema.sql` | PostgreSQL 用户画像、原始资料、记忆、证据、版本和策略表 |
| `postgresql_chat_schema.sql` | PostgreSQL 聊天会话、参与者和真实消息表 |
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

在仓库根目录执行：

```powershell
python backend/scripts/init_db.py
```

默认数据库文件为 `backend/data/twinloop.db`。指定数据库路径：

```powershell
python backend/scripts/init_db.py --database backend/data/dev.db
```

SQLite 结构用于本地开发和测试；PostgreSQL 脚本是独立实现，不能直接把 PostgreSQL SQL 当作 SQLite SQL 执行。

## 数据安全和维护注意事项

- 原始知乎内容和聊天消息可能包含个人隐私，生产环境应限制数据库账号权限并做好备份加密。
- 不要把密码、访问令牌或第三方 OAuth token 直接写入 `content` 或普通 `metadata` 字段。
- 画像推断结果不能默认当作用户事实；读取时应检查 `status` 和 `confidence`。
- 业务代码更新会话的 `updated_at`，写入消息时应在同一事务中更新会话时间。
- 删除用户时，画像和聊天记录会按外键级联删除；执行前应确认这符合数据保留政策。
- 新增数据库表或字段后，应同步补充本 README 和根目录 `AGENTS.md` 中的说明。
