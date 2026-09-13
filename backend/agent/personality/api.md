# 性格测评接口

当前 FastAPI 原型提供以下接口：

```text
GET  /v1/personality/questions
POST /v1/personality/assessments
POST /v1/personality/skip
GET  /v1/personality/assessments/latest
```

提交答案示例：

```json
{
  "answers": {"E01": 4, "E02": 3, "E03": 5},
  "notes": "可选的自我说明",
  "request_key": "客户端幂等键"
}
```

答案使用 1–5 分，允许部分提交；少于 40 题时结果会标为 `partial`，完整但完全同一选项的作答会标为 `quality_review`，某些维度缺失时 `usable=false`。所有结果仍保存为私有测评记录。跳过测评时五维分数为 `null`，不会由系统补造人格分数。

提交后，结果写入画像的 `personality` 字段。发布 `/v1/twin/versions` 时：

- `data.personality` 保存可读的 Big Five 渲染文本；
- `data.extensions.twin.personality` 保存分数、版本、状态和风格标签；
- 原始答案、备注和效度明细不会进入角色卡扩展。
