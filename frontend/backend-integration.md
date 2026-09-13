# 前后端对接契约（v0.2）

本文件是前端调用传统后端的唯一对接说明，完整内容见 [backend/app/integration.md](../backend/app/integration.md)。

前端只通过 `/api/v1` HTTP API 和 SSE 获取业务状态。登录、知乎 OAuth、原始数据、画像版本、权限、预算、删除和审计全部由传统后端负责。

核心流程：

```text
GET /me
→ POST /sources/zhihu/connect
→ POST /initializations
→ GET /initializations/:id（轮询或 SSE）
→ GET /avatars/:id/draft
→ PATCH /avatars/:id/draft
→ POST /avatars/:id/versions
→ GET /avatars/:id/profile
```

前端必须根据后端返回的 `loading`、`processing`、`review`、`ready`、`paused`、`failed`、`revoked` 状态渲染页面，不得自行推断任务成功。所有记忆展示都应保留来源、`depth`、确认状态和 `share` 字段。

前端不得保存知乎 Token、直接访问 Agent/数据库/向量库，或把 Agent 生成的消息标记为真人消息。
