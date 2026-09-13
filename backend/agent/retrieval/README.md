# 检索编排

负责问题分析、查询改写、关键词/向量并行检索、权限过滤、去重、冲突处理、排序和上下文截断。检索器只接收传统后端提供的索引接口。

## 当前实现

`service.py` 只提供可显式调用的 PostgreSQL + Chroma 分层检索函数：短的固定画像直接查 PostgreSQL，经历、原始资料和聊天记录先合并 PostgreSQL 关键词候选与 Chroma 向量候选，再回 PostgreSQL 取完整内容。数据库连接和向量适配器均由调用方注入，不在 Agent 内部创建连接或读取用户 Token。

这些函数不是 Agent Tool，也不会被模型自动发现或调用。应用在自己的“问题分析 → 组装上下文”流程中明确调用它们，得到结构化结果后再交给 Prompt 层。

- `analyze_question(question)`：生成主题、意图和检索需求。
- `repository.get_fixed_profile(user_id)`：读取当前生效的身份、性格、表达风格和策略。
- `search_long_memories(...)`：PostgreSQL 关键词 + Chroma 向量混合检索长记忆。
- `search_source_documents(...)`：混合检索原始知乎资料，向量库只返回候选 ID。
- `search_chat_history(...)`：混合检索聊天消息并扩展同会话前后文窗口。
- `build_context(...)`：由调用方显式调用，组装固定画像和全部动态检索结果。

向量适配器位于 `backend/agent/adapters/vector_search.py`。`ChromaVectorSearchAdapter` 只负责调用 Chroma、生成候选分数和写入/删除向量；完整内容、权限、状态和审计始终以 PostgreSQL 为准。Chroma Payload 中应保存原始记录 ID、`avatar_id`、集合对应的类型，以及 Embedding 模型名称和维度，便于模型切换和重建索引。

返回结果不会直接拼成 Prompt 字符串，调用方可将 `profile`、`retrieved_memories`、`source_documents` 和 `chat_history` 分区交给 Prompt 层处理。检索会过滤拒绝、过期、敏感和不可用内容，并优先返回已确认内容。

示例（连接工厂由应用注入）：

```python
from agent.retrieval.service import PostgresRetrievalRepository, build_context

repository = PostgresRetrievalRepository(connection_factory)
context = await build_context(user_id, question, repository)
```
当前 Agent 只负责问题分析、查询改写和上下文需求契约；不实现 embedding、向量数据库或索引。PostgreSQL 检索仓储由传统后端注入连接工厂，Agent 只在上下文组装流程中显式调用，并继续负责去重、冲突处理、排序和上下文截断。


检索 SQL 使用连接的 search_path，不再写死 public schema；生产环境默认 search_path=public，测试可注入临时 schema。
