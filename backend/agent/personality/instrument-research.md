# 测评依据与实现说明

首版采用 Lewis R. Goldberg 的 International Personality Item Pool（IPIP）公开领域 Big-Five Factor Markers。IPIP 官方说明允许任何人出于商业或非商业目的使用其题目、量表和测验；官方计分说明规定五点量表使用 1–5 分，负向条目反向计分后求和或求均值。

本实现使用官方 10-item broad-factor markers 的五个维度，共 50 题：外向性、宜人性、尽责性、情绪敏感性和开放性。官方报告的英文版本内部一致性仅作为量表背景信息，不直接宣称本中文翻译已经具有相同信度。

`ipip-big-five-50-zh-v1` 是产品使用的中文翻译版本。题目 ID、维度和正负向键与公开英文标记保持对应，中文措辞、文化可理解性和测量等价性仍需通过中文样本的认知访谈、试测、内部一致性和重测研究验证。

系统区分三类结果：`scores` 是按 IPIP 规则计算的维度分数；`validity` 是漏答和机械作答等响应质量检查；`confidence`/`data_quality` 只表示本次数据完整性和质量，不是临床诊断或已验证的总体人格真值概率。

每题使用 1–5 分：非常不符合、较不符合、一般、较符合、非常符合。负向条目转换为 `6 - answer`，每个维度的原始均值映射到 0–10：

```text
score_0_10 = (mean_1_5 - 1) × 2.5
```

原始答案只存于私有测评记录，不进入普通角色卡提示词；角色卡保存 0–10 分、测评版本和规则生成的风格标签。

来源：

- https://ipip.ori.org/newBigFive5broadKey.htm
- https://ipip.ori.org/newPermission.htm
- https://ipip.ori.org/newScoringInstructions.htm
