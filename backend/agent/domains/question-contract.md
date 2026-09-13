# 选择题契约示例

```json
{
  "question_id": "q_rag_001",
  "question_version": 1,
  "domain_id": "computer.03.03",
  "question_type": "applied_tradeoff",
  "prompt": "企业 RAG 在成本、可靠性和速度之间如何上线？",
  "options": [
    {"id": "opt_a", "label": "统一使用最强模型，优先保证质量"},
    {"id": "opt_b", "label": "按风险分级：普通请求使用小模型，高风险请求升级并人工审核"},
    {"id": "opt_c", "label": "统一使用小模型，优先保证成本和速度"},
    {"id": "opt_custom", "label": "其他/自定义答案", "requires_custom_text": true},
    {"id": "opt_unknown", "label": "不知道或暂时无法判断", "scoring": "uncertain"}
  ],
  "response": {"selected_option_id": "opt_b", "custom_text": null}
}
```

服务端保存题目版本和原始选项 ID，再由 Agent 生成 `stance_record`、`knowledge_score` 与 `reasoning_observation`。自定义文本只补充用户选择，不替代选择题结构。
# 高区分度观点题示例

情境：你的团队发现 RAG 的引用准确率为 92%，继续提高到 97% 会让延迟翻倍。你支持哪种上线策略？

- A：所有场景达到 97% 后再上线。
- B：按风险分级，低风险接受 92%，高风险升级模型并要求引用或人工审核。
- C：先上线 92% 版本，用真实反馈换取后续改进。
- D：其他/自定义答案（填写具体方案）。
- E：不知道或暂时无法判断。

该题主要识别可靠性与速度的价值排序、风险分层意识和证据门槛；只有用户提到准确率定义、评估集或延迟测量时，才记录辅助 knowledge_signal。没有唯一正确选项。
