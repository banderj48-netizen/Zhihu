# TwinLoop 后端联调手册

## 1. 安装与数据库

在 `backend` 目录创建虚拟环境并安装依赖：

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -e ".[test]"
```

设置 `backend/.env`（数据库和应用配置）：

```text
DATABASE_URL=postgresql://postgres:密码@localhost:5432/zhihu
TWINLOOP_MOCK_LLM=true
```

模型配置单独保存到 `backend/.env.models`：

```powershell
Copy-Item backend/.env.models.example backend/.env.models
# 编辑 backend/.env.models，填写 LLM_API_KEY、EVALUATOR_LLM_API_KEY 和 EMBEDDING_API_KEY
```

也可以设置 `TWINLOOP_MODEL_ENV_FILE` 指向其他模型环境文件。真实密钥不会提交 Git。

首次建表：

```powershell
python -c "from db.database import initialize_formal; initialize_formal()"
```

## 2. 启动服务

```powershell
uvicorn app.main:app --reload --port 8000
```

前端无需改动。开发调试可使用 `X-User-Id`，生产环境必须使用 OAuth 会话 Cookie。

## 3. 初始化顺序

1. `POST /v1/twin/initializations`
2. `POST /v1/twin/initializations/{id}/{step}` 保存身份、性格答案、领域和答题结果。
3. `POST /v1/twin/initializations/{id}/complete` 完成初始化。
4. 查询画像/角色卡接口，确认 active 版本和 `chara_card_v2`。

领域题和社交题的原始选择会进入 `source_documents`；有效社交答案必须在服务端计算的 13 秒内，超时只保留审计信息。

## 4. Agent 写入工具

Agent 只能提交 `propose_*` 工具提案。后端会检查用户归属、版本号、隐私、幂等键并创建新版本；冲突返回 409。固定画像、初始化和聊天消息由普通后端函数写入。

## 5. 检索与同步

PostgreSQL 是事实源。画像或原始资料提交后会产生 `vector_sync_outbox`，worker 成功后再写入 Chroma。未配置 Chroma 时使用空/契约适配器，不能据此判断真实向量质量。

## 6. 验收

```powershell
python -m compileall -q backend/agent backend/app
python -m pytest backend/agent/personality/test_assessment.py backend/tests/test_retrieval_integration.py
```

启用 PostgreSQL 集成测试时，先设置独立测试数据库连接（测试会自动创建并清理临时 schema）：

```powershell
$env:TWINLOOP_TEST_DATABASE_URL="postgresql://postgres:密码@localhost:5432/zhihu"
python -m pytest backend/tests/test_retrieval_integration.py -q
```

测试不会使用旧 SQLite 数据库，也不会修改前端或现有生产 schema。

重点检查：版本递增、超时答案排除、原始证据关联、私密隔离、聊天序号幂等、outbox 重试和角色卡 JSON 可序列化。

真实 Chroma 需要在应用中注入 `ChromaVectorSearchAdapter`（客户端和 embedding 模型）；未注入时系统使用契约/空适配器，检索仍可走 PostgreSQL，但不代表完成向量质量验证。
