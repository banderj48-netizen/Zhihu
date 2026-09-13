# 画像写入边界

`ProfileRepository` 是传统后端使用的 PostgreSQL 写入仓储。Agent 只能构造 `ProfileProposal`，不能获得数据库连接。每次有效提案创建完整 `avatar_versions` 快照并激活新版本；原始资料写入 `source_documents`，动态世界书写入 `avatar_memories`，聊天原文写入 `chat_messages`。Chroma/outbox 同步在下一层基础设施接入，不能绕过 PostgreSQL 事实源。
