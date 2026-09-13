# Agent 子系统

本目录是 TwinLoop 的数字分身 Agent 独立边界，与传统后端的用户、授权、导入、数据库和 HTTP API 分离。

这里只负责：画像上下文编排、性格评测推理、领域情景题、三层记忆召回、提示词渲染、模型调用、输出约束和 Agent 评测。

传统后端通过稳定接口向本目录提供用户画像快照、证据、权限和任务事件；Agent 不直接访问数据库或知乎 OAuth。

开发顺序和跨边界信息交换见：

- `architecture/development-strategy.md`
- `contracts/backend-integration.md`
- `contracts/data-contracts.md`
