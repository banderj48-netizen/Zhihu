# Agent Runtime

负责对话回合编排、模型适配、输出结构化、反编造检查、连贯性检查、卡壳检测和事件回传。运行时不直接写正式画像。
# Agent 运行时

`llm.py` 提供可注入请求函数的 `LLM` 类，负责统一异步模型调用结果。

`agent.py` 提供 `Agent` 类，负责显式调用上下文组装函数、按分区构建 Prompt、调用 LLM 和返回回答元数据。

Agent 不注册工具，也不会主动访问数据库或 Chroma。检索由调用方注入的 `context_builder` 完成。

## 模型构建

`model_builder.py` 提供 `build_llm()`，从 `backend/.env` 读取 `LLM_API_KEY`、`LLM_BASE_URL` 和 `LLM_MODEL`，并构造 OpenAI 兼容协议的 `LLM`。环境变量优先于 `.env`，也兼容 `OPENAI_API_KEY`、`OPENAI_BASE_URL` 和 `OPENAI_MODEL` 命名。

```python
from agent.runtime.model_builder import build_llm

llm = build_llm()
response = await llm.generate("请回答问题")
```

不要将真实 API Key 提交到 Git；请复制 `backend/.env.example` 为 `backend/.env` 后填写配置。

## 双 Agent 对话

`agent_graph.py` 使用 LangGraph 编排上下文准备、模型调用、行为记忆工具和回合结束；`dialogue.py` 负责 A/B 交替对话与 PostgreSQL/Chroma 消息持久化。执行前需先运行 `backend/db/postgresql_agent_dialogue.sql`。
## 初始化与反馈

`initialization.py` 复用既有导入、性格测评和 `ProfileRepository`，负责创建唯一初始化会话及初始画像；`mind_reading.py` 保存无记忆命中后的心灵感应题反馈。FastAPI 路由集中在 `api.py`，检索仍由业务显式调用，Agent 不会自主访问数据库。

`matching.py` 提供当前场景候选的随机、手动和 LLM 匹配策略；双 Agent 运行状态及评判结果由 `dialogue.py` 写入既有业务表。

`topic_gate.py` 在对话开始前比较双方高置信度观点，选择共同话题或随机试探话题，并由接收方先判断兴趣；低兴趣会写入拒绝消息并立即结束 LangGraph 流程。

`chat_groups.py` 提供聊天组统计、分页列表和完整消息查询；聊天组由 `dialogue.py` 在每次运行开始时创建，并以 `chat_no` 作为用户查询标识。
# 双 Agent 实时运行

`DialogueManager` 负责后台任务、最多 10 组并发、取消信号和 SSE 事件；`PresenceService` 负责场景空闲池，并保证当前登录用户的 avatar 永远作为发起方 A。前端通过 `/v1/twin/dialogues/{run_id}/events` 接收 `run_started`、`topic_selected`、`message`、`round_progress`、`evaluation` 和终态事件。

聊天组只有在 PostgreSQL 消息全部落库后才会变为 `processing_status=ready` 并出现在历史接口；Chroma 失败不会回滚事实消息。每日对话终态后调用 `POST /v1/twin/dialogues/{run_id}/advance-day` 回到地图选择。
