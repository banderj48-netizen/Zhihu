# 传统后端与 Agent 信息交换

## 边界角色

传统后端（`backend/app`）负责认证、授权、知乎数据、数据库、版本、删除和审计。

Agent（`backend/agent`）负责候选抽取、评测解释、领域和记忆推理、检索需求、Prompt、模型调用和输出校验。RAG、向量化和索引由独立服务实现，不属于本目录。

## 初始化阶段通信

### 1. 创建初始化会话

传统后端 → Agent：不需要调用 Agent。传统后端创建 `initialization_id` 并管理状态。

### 2. 原始数据导入

传统后端内部完成 OAuth、读取个人简介和回答、原始保存、清洗和证据切片。Token 和原始响应不发送给 Agent。

### 3. 请求候选抽取

传统后端 → Agent：发送初始化 ID、画像 ID、允许用途、证据片段和数据版本。

```json
{
  "contract_version": "agent.init.extract.v1",
  "initialization_id": "init_001",
  "avatar_id": "avatar_001",
  "allowed_purposes": ["identity", "expertise", "interest", "opinion", "behavior", "style"],
  "evidence": [
    {
      "evidence_id": "ev_001",
      "document_id": "answer_001",
      "content_type": "answer",
      "text": "证据片段",
      "source_url": "https://example.invalid",
      "created_at": "2026-09-13T10:00:00Z",
      "privacy": "private"
    }
  ]
}
```

Agent → 传统后端：返回候选实体、证据引用、状态、置信度、领域和质量报告。初始状态只能是 `source_observed` 或 `unconfirmed`，不能直接返回 `confirmed`。

### 4. 可选性格测评

前端将题目答案提交给传统后端；传统后端把题目版本和答案传给 Agent 计分接口。Agent 返回分数、置信度、效度和解释，传统后端保存测评记录。

跳过测评时，传统后端传 `assessment_status=skipped`，Agent 不得自行补造人格分数。

### 5. 三层记忆建议

传统后端 → Agent：发送已保存的候选实体和证据摘要。

Agent → 传统后端：返回记忆层级建议、触发条件、例外、观察依据和置信度。传统后端负责保存候选及其审核状态。

### 6. 一次性总确认

传统后端将候选汇总给用户。用户整体确认、修改、跳过或重新生成后，传统后端保存审核事件。

- 整体确认：候选转为 `confirmed`。
- 跳过：候选保持 `unconfirmed`，但允许 Agent 使用。
- 拒绝：转为 `rejected`，之后不得召回。
- 删除：转为 `deleted`，并触发清理事件。

### 7. 生成版本

传统后端根据审核结果生成不可变画像版本，再调用 Agent 的卡片渲染接口。Agent 返回 `chara_card_v2` 投影，传统后端保存版本和发布记录。

## 运行时通信

### 请求回答

传统后端 → Agent：发送当前用户消息、场景、对话历史、画像快照引用、检索策略和上下文预算。Agent 通过适配器向传统后端请求允许召回的记忆和证据。

### 返回回答

Agent → 传统后端：

```json
{
  "contract_version": "agent.chat.reply.v1",
  "answer": "回复文本",
  "confidence": 0.72,
  "used_memory_ids": ["memory_003"],
  "evidence_refs": ["ev_001"],
  "deadlock_signals": [],
  "correction_proposal": null
}
```

传统后端保存对话事件和 Agent 元数据；是否向用户展示引用和置信度由产品层决定。

## 持续校准通信

用户纠正、卡壳、情境题答案和“都不准确”反馈由传统后端记录为事件，再发送给 Agent 分析。Agent 只能返回：

```text
evidence_update
memory_proposal
personality_change_proposal
question_proposal
```

传统后端负责权限检查、用户确认、正式落库和新版本生成。

## 删除和撤销

传统后端发布 `source_revoked` 或 `avatar_deleted` 事件，包含受影响的 source/document/evidence ID。Agent 停止使用相关结果；独立 RAG 服务负责删除自己的向量和索引。事件完成前，相关内容不得继续召回。

## 错误和幂等

所有请求携带 `request_id`、`contract_version` 和 `idempotency_key`。Agent 需要区分：

- `INVALID_CONTRACT`：契约版本或字段错误，不重试；
- `POLICY_DENIED`：权限或隐私不允许，不重试；
- `SOURCE_UNAVAILABLE`：证据暂时不可用，可由传统后端重试；
- `MODEL_TIMEOUT`：模型超时，按降级策略处理；
- `MODEL_INVALID_OUTPUT`：模型格式错误，可有限重试；
- `DELETED_SOURCE`：来源已删除，立即停止使用。

任何重复请求都不能重复写入画像版本或重复生成审核事件。
