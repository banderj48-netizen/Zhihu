# 检索编排

负责问题分析、查询改写、关键词/向量并行检索、权限过滤、去重、冲突处理、排序和上下文截断。检索器只接收传统后端提供的索引接口。

## 当前实现

`service.py` 只提供可显式调用的 PostgreSQL 检索函数，数据库连接通过 `PostgresRetrievalRepository` 注入，不在 Agent 内部创建连接或读取用户 Token。

这些函数不是 Agent Tool，也不会被模型自动发现或调用。应用在自己的“问题分析 → 组装上下文”流程中明确调用它们，得到结构化结果后再交给 Prompt 层。

- `analyze_question(question)`：生成主题、意图和检索需求。
- `repository.get_fixed_profile(user_id)`：读取当前生效的身份、性格、表达风格和策略。
- `repository.search_memories(...)`：按观点、行为、专长和兴趣分类返回动态记忆。
- `repository.search_source_documents(...)`：通过 PostgreSQL 全文检索和关键词检索原始知乎内容。
- `repository.search_chat_history(...)`：检索数字分身参与过的历史聊天消息。
- `build_context(...)`：由调用方显式调用，并行执行固定画像、动态记忆、原始资料和聊天历史检索，返回结构化上下文。

返回结果不会直接拼成 Prompt 字符串，调用方可将 `profile`、`retrieved_memories`、`source_documents` 和 `chat_history` 分区交给 Prompt 层处理。检索会过滤拒绝、过期、敏感和不可用内容，并优先返回已确认内容。

示例（连接工厂由应用注入）：

```python
from agent.retrieval.service import PostgresRetrievalRepository, build_context

repository = PostgresRetrievalRepository(connection_factory)
context = await build_context(user_id, question, repository)
```
当前 Agent 只负责问题分析、查询改写和上下文需求契约；不实现 embedding、向量数据库或索引。PostgreSQL 检索仓储由传统后端注入连接工厂，Agent 只在上下文组装流程中显式调用，并继续负责去重、冲突处理、排序和上下文截断。
