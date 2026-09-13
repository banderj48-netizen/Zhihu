# 项目协作说明

- 新增数据库脚本默认使用 UTF-8 编码，并使用中文表注释和字段注释。
- PostgreSQL 数字分身相关脚本位于 `backend/db/`，执行前应先连接 `zhihu` 数据库。
- 当前业务约束为一个用户只能拥有一个数字分身，相关表必须保留唯一约束。
- 聊天记录必须保存真实消息内容、消息时间、稳定 ID、会话内顺序和发送者信息；删除优先采用软删除。
- `backend/agent/retrieval/service.py` 只提供供上下文组装流程显式调用的检索函数，不注册为 Agent Tool，Agent 不得自主触发数据库检索。
- 短固定画像直接查 PostgreSQL；经历、原始资料和聊天记录使用 PostgreSQL 关键词与 Chroma 向量混合检索，向量库只保存候选 ID 和检索元数据。
- `backend/agent/runtime/llm.py` 和 `agent.py` 中的 LLM、Agent 类必须通过依赖注入工作；Agent 不注册检索工具，不主动访问数据库或向量库。
- `backend/agent/runtime/model_builder.py` 从 `backend/.env` 或环境变量读取 LLM API Key、URL 和模型名，禁止在代码中硬编码密钥。
- LangGraph 双 Agent 运行状态和评判结果使用 `backend/db/postgresql_agent_dialogue.sql` 建表；A/B 消息仍写入 `chat_messages`，Chroma 只保存向量和元数据。
- 双 Agent 对话默认最多同时运行 10 个、每次最多 10 轮；达到 `GREAT_SCORE` 时只调用推送接口占位实现。
- 修改或新增数据库模块后，应同步更新本文件中的约束和执行说明。
- 数字分身初始化状态、心灵感应反馈和性格调整表位于 `backend/db/postgresql_twin_initialization.sql`，需在聊天与画像脚本之后执行。
- 初始化、匹配和反馈 API 位于 `backend/agent/runtime/api.py`，统一通过服务层调用，禁止在路由中直接操作 Chroma。
- 双 Agent 开场话题门控位于 `backend/agent/runtime/topic_gate.py`：共同观点优先，无共同观点时随机试探；接收方兴趣分数低于阈值时正常结束，不进入后续对话。
