# 现实社交情景题契约

领域题记录用户在主题上的观点与判断标准；社交情景题记录具体人际场景中的下意识反应、边界和条件。两者都不直接修改 Big Five。

社交题由服务端生成 `presented_at`，限时 13 秒。提交时由服务端计算耗时；超过 13 秒、缺少选择或时间无效，记为 `timeout/invalid`，不计入一致率、人格证据或记忆提案，但可保留审计事件。

```json
{
  "question_id": "social_001",
  "question_version": 1,
  "question_type": "social_situation",
  "scene": "刚认识的同事在多人聊天中把一个明显错误归因到你负责的模块。",
  "options": [
    {"id": "opt_a", "label": "马上打断，直接纠正事实"},
    {"id": "opt_b", "label": "先让对方说完，私下补充证据"},
    {"id": "opt_c", "label": "先不争论，观察是否影响实际决定"},
    {"id": "opt_custom", "label": "其他/自定义答案", "requires_custom_text": true}
  ],
  "response": {"presented_at":"2026-09-13T10:00:00Z","submitted_at":"2026-09-13T10:00:08.421Z","selected_option_id":"opt_b","custom_text":null}
}
```

写入后续 RAG 的 memory proposal 应包含 `scene`、`trigger`、`default_reaction`、`conditions`、`exceptions`、`source_question_id`、`response_latency` 和 `confidence`，默认 private/share=false/unconfirmed。深层保存稳定原则，中层保存 if-then 条件反应，浅层保存最近先例；RAG 自行切片、向量化和检索。
