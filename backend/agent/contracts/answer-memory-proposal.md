# 用户领域回答交给 RAG 的契约

Agent 的工作终点是结构化提案；不负责向量数据库。传统后端负责鉴权、幂等、版本和落库，后续 RAG 服务自行订阅。

```json
{
  "contract_version": "agent.answer.memory-proposal.v1",
  "proposal_id": "proposal_001",
  "avatar_id": "avatar_001",
  "question_id": "question_001",
  "domain_id": "computer.03.03",
  "answer": "……",
  "answer_status": "answered",
  "stance_record": {"position": "有条件支持", "summary": "……", "conditions": [], "exceptions": [], "confidence": 0.72},
  "knowledge_score": {"status": "scored", "score": 0.68, "rubric_version": "question-001-rubric-v1", "uncertainty": []},
  "reasoning_observation": {"evidence_use": "partial", "tradeoff_awareness": "high"},
  "evidence_refs": ["ev_001"],
  "privacy": "private", "share": false, "confirmation_status": "unconfirmed",
  "created_at": "2026-09-13T10:00:00Z"
}
```

`position` 与 `knowledge_score` 必须分开；“不知道”“不适用”“都不符合”是合法选项；“其他/自定义答案”必须带 custom_text。单次回答不得直接改变人格分数或确认长期记忆。
