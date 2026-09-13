# 前后端对接契约（v0.2）

本文是传统后端 `backend/app` 与前端 `frontend` 的对接约定。传统后端是权限、持久化和状态的唯一事实来源；前端只通过 HTTP API 和 SSE 读取、修改业务状态。

## 通用约定

- API 前缀：`/api/v1`
- 请求使用 JSON；时间使用 ISO 8601 UTC。
- 所有写请求携带 `request_id`，需要幂等的操作额外携带 `idempotency_key`。
- 认证使用 HttpOnly、Secure 会话 Cookie；前端不接触知乎 Token。
- 响应统一包含 `request_id`、`data` 或 `error`。
- 资源状态由后端返回，前端不得自行推断成功。

## 登录和当前用户

### `GET /api/v1/me`

前端启动时调用，返回当前用户和数字分身状态。

```json
{
  "data": {
    "user_id": "user_001",
    "avatar_id": "avatar_001",
    "avatar_status": "not_created|processing|review|ready|paused",
    "zhihu_connected": false
  }
}
```

## 知乎授权和初始化

### `POST /api/v1/sources/zhihu/connect`

创建知乎授权地址。后端负责 OAuth state、Token 和回调校验。

```json
{
  "scopes": ["profile", "answers"]
}
```

返回：

```json
{
  "data": { "authorization_url": "https://...", "state_id": "state_001" }
}
```

### `POST /api/v1/initializations`

创建数字分身初始化任务。后端读取已授权的知乎简介和回答，保存原始内容、清洗内容和证据片段，再调用 Agent。

```json
{
  "source": "zhihu",
  "allowed_purposes": ["identity", "expertise", "interest", "opinion", "behavior", "style"],
  "include_profile": true,
  "include_answers": true
}
```

返回：

```json
{
  "data": { "initialization_id": "init_001", "status": "fetching" }
}
```

### `GET /api/v1/initializations/{initialization_id}`

返回任务进度：

```json
{
  "data": {
    "initialization_id": "init_001",
    "status": "fetching|storing_raw|extracting|review|completed|failed",
    "progress": 65,
    "counts": { "documents": 214, "evidences": 680 },
    "error": null
  }
}
```

### `GET /api/v1/avatars/{avatar_id}/draft`

返回 Agent 生成、尚未正式生效的画像草稿。每一项都包含来源、置信度、确认状态和隐私设置。

### `PATCH /api/v1/avatars/{avatar_id}/draft`

前端提交用户整体确认、修改、跳过或拒绝。请求必须携带 `revision`，后端使用乐观锁。

```json
{
  "revision": 3,
  "action": "confirm|skip|regenerate",
  "changes": [
    {
      "entity_id": "claim_001",
      "status": "confirmed",
      "content": "用户修改后的内容",
      "share": false
    }
  ]
}
```

### `POST /api/v1/avatars/{avatar_id}/versions`

用户完成确认后生成不可变画像版本。后端保存版本，再调用 Agent 生成 `chara_card_v2` 投影。

## 画像和记忆

### `GET /api/v1/avatars/{avatar_id}/profile`

返回当前生效版本的身份、专业、兴趣、观点、行为记忆和表达风格。

### `GET /api/v1/avatars/{avatar_id}/memories`

支持 `type`、`status`、`privacy`、`page`、`page_size` 筛选。返回的记忆必须包含 `depth`：`deep`、`middle` 或 `shallow`，以及 `evidence_refs`。

### `PATCH /api/v1/memories/{memory_id}`

确认、编辑、隐藏或删除一条记忆。后端校验 owner、版本和来源状态。

## 场景和内容

### `GET /api/v1/scenes`

返回当前可用场景。P0 只有 `lecture_hall`（演讲厅）和 `cafe`（咖啡厅）。

### `GET /api/v1/scenes/{scene_id}/content`

返回当前用户有权阅读的场景内容、来源、许可范围和版本。

## 探索、进度和相遇

### `POST /api/v1/explorations`

创建一次探索计划。后端检查画像版本、场景许可、当下意图、预算和暂停状态。

```json
{
  "avatar_version": 1,
  "scene_id": "lecture_hall",
  "intent": "想认识聊得来的人",
  "content_ids": ["content_001"],
  "budget": { "max_rounds": 7 }
}
```

### `POST /api/v1/episodes/{episode_id}/pause`

持久化暂停当前交流片段。

### `POST /api/v1/episodes/{episode_id}/resume`

恢复前重新检查授权、版本、预算和来源是否仍然有效。

### `GET /api/v1/explorations/{exploration_id}/events`

通过 SSE 返回进度、检查点、消息、未知项和错误。断线后使用 `Last-Event-ID` 续传。

### `GET /api/v1/encounters/{encounter_id}`

返回相遇卡、共同话题、差异、未解问题、证据来源和 AI 标识。私密报告只能返回给对应用户。

## 真人连接

### `POST /api/v1/connection-requests`

发送经过用户审核的介绍申请。后端检查双方授权、版本一致、黑名单和幂等键。

### `POST /api/v1/connection-requests/{request_id}/respond`

接受、拒绝或暂缓。状态转换由后端原子执行。

### `POST /api/v1/connections/{connection_id}/messages`

双方真人建立连接后发送消息。Agent 默认不能代发或读取真人聊天内容。

## 全局控制和删除

### `POST /api/v1/avatars/{avatar_id}/pause`

暂停分身新行动；在途模型结果不得提交。

### `DELETE /api/v1/sources/{source_id}`

删除来源及其文档、证据、向量、画像引用和派生缓存，并通知 Agent 清理。

### `DELETE /api/v1/avatars/{avatar_id}`

删除分身及其所有派生数据。后端返回清理任务状态，不能只删除前端展示。

## 前端必须处理的状态

```text
loading
empty
processing
review
ready
paused
waiting_owner
failed
revoked
```

错误响应至少包含：`code`、`message`、`retryable`、`request_id`。前端遇到 `409 REVISION_CONFLICT` 应重新读取数据；遇到 `403 POLICY_DENIED` 不得自动重试。

## 不属于前端职责的内容

前端不得保存知乎 Token，不得直接访问 Agent、数据库或向量库，不得自行修改权限、预算、版本和任务状态，也不得把分身消息标记为真人消息。
