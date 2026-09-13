# Agent 数据契约清单

首版至少需要固定以下 DTO：

```text
InitializationExtractRequest
CandidateProfileEntity
PersonalityAssessmentRequest
PersonalityAssessmentResult
MemoryLayerProposal
AvatarRuntimeContext
MemorySearchRequest
MemorySearchResult
PromptRenderRequest
AgentReply
AgentEvent
CorrectionProposal
DeletionEvent
```

每个 DTO 必须包含：

- `contract_version`；
- `request_id` 或 `event_id`；
- `avatar_id` 和必要的 `user_id` 引用；
- `privacy`/`share` 策略结果；
- `source_ids` 或 `evidence_refs`；
- 创建时间和数据版本。

Agent 不接收不必要的 PII。能用 `avatar_id`、证据 ID 和脱敏片段完成的请求，不发送完整身份资料。
