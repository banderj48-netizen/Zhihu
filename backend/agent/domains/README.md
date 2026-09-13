# 领域 Agent

领域用于决定检索范围和情景题方向，不直接推断人格或政治立场。

目录使用稳定 ID、版本、层级、别名、边界和描述；覆盖 18 个根域、约 100 个分类和 500 个可选叶子。兴趣（0–3）与擅长领域（自评熟悉度）独立保存，均默认为 `private/share=false`；自评不能生成 verified expertise。接口：`GET /v1/domains`、`GET /v1/domains/{id}`、`GET /v1/domains/selections/me`、`PUT /v1/domains/selections/me`。PUT 使用 `expected_revision` 乐观锁，传空数组表示清除选择。
