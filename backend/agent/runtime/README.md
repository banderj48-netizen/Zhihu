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
