# 传统后端数据能力调用接口

本文面向 Agent 系统开发者。目标是把传统后端已经实现的数据获取函数封装成稳定能力，Agent 通过能力接口调用它们；Agent 只负责编排、理解和生成，不能直接访问知乎、数据库或会话 Token。

## 总体调用关系

```text
前端 POST
  ↓
传统后端 API 路由
  ↓
Agent Runtime
  ↓
BackendDataProvider（后端数据能力适配器）
  ↓
传统后端现有 service / repository / imports 函数
  ↓
返回脱敏、授权后的数据
```

前端只调用传统后端的业务 API。传统后端内部再把请求路由给 Agent；前端不直接调用 Agent 的内部能力接口。

## 设计原则

1. Agent 调用的是能力接口，不调用具体函数实现。
2. 传统后端负责身份、授权、Token、数据获取和持久化。
3. 每次调用都由后端根据会话确定 `user_id`，Agent 不可信任前端传入的用户 ID。
4. 知乎 Token 只在传统后端内部使用，绝不返回 Agent 或前端。
5. 返回 Agent 的数据必须经过用途、来源、隐私、删除状态和有效期过滤。
6. 所有返回内容都要带来源 ID，便于 Agent 引用和后端审计。

## 能力接口

### 1. 获取当前用户知乎资料

能力名：`get_current_zhihu_profile`

后端内部实现可复用：`auth.repository.get_by_id`、`auth.service.to_me_payload`。

输入：

```json
{
  "request_id": "req_001",
  "avatar_id": "avatar_001"
}
```

输出：

```json
{
  "user_id": "user_001",
  "avatar_id": "avatar_001",
  "profile": {
    "fullname": "用户昵称",
    "headline": "个人签名",
    "avatar_url": "https://..."
  },
  "zhihu_connected": true,
  "source": "zhihu_profile"
}
```

用途：身份摘要、分身基础资料。Agent 不得据此推断敏感属性。

### 2. 获取知乎内容

能力名：`list_zhihu_contents`

后端内部实现：`imports.service.list_contents`，通过 `imports.router.GET /api/v1/imports/contents` 暴露给传统后端调用层。

输入：

```json
{
  "request_id": "req_002",
  "avatar_id": "avatar_001",
  "content_types": ["answer"],
  "limit": 20,
  "offset": 0,
  "purpose": "identity|expertise|interest|opinion|behavior|style"
}
```

输出：

```json
{
  "items": [
    {
      "document_id": "doc_001",
      "source_id": "answer_123",
      "content_type": "answer",
      "title": "问题标题",
      "question": "问题文本",
      "content": "回答文本",
      "created_at": "2025-03-15T10:00:00Z",
      "source_url": "https://www.zhihu.com/...",
      "privacy": "private",
      "share": false
    }
  ],
  "paging": { "limit": 20, "offset": 0, "has_more": true }
}
```

Agent 用它提取身份、专业、兴趣、观点、行为和表达风格。`content` 必须是已授权且可用于当前 `purpose` 的内容。

### 3. 获取关注用户

能力名：`list_zhihu_followees`

后端内部实现：`imports.service.list_followees`。

输入：

```json
{
  "request_id": "req_003",
  "avatar_id": "avatar_001",
  "limit": 20,
  "offset": 0,
  "purpose": "interest"
}
```

输出中的关注关系只能作为兴趣线索，不能直接当作用户认同对方全部观点：

```json
{
  "items": [
    {
      "source_id": "followee_001",
      "name": "关注对象",
      "headline": "公开签名",
      "url_token": "token",
      "source": "zhihu_followee"
    }
  ]
}
```

### 4. 获取收藏夹和收藏内容

能力名：`list_zhihu_favlists`、`list_zhihu_favlist_contents`

后端内部实现：`imports.service.list_favlists`、`imports.service.list_favlist_contents`。

收藏只能作为弱兴趣信号。Agent 不得把收藏内容直接写成用户观点。

### 5. 获取用户专栏/集合内容

能力名：`list_zhihu_collections`

后端内部实现：`imports.service.list_recent_collections`。

输出必须带 `source_id`、标题、摘要或正文、时间和授权范围。只允许在授权用途内使用。

### 6. 获取已保存的画像快照

能力名：`get_avatar_snapshot`

后端内部实现：`profiles` 和 `memories` 模块的查询服务。

输入：

```json
{
  "request_id": "req_004",
  "avatar_id": "avatar_001",
  "avatar_version": 1,
  "include": ["identity", "personality", "expertise", "interests", "opinions", "behavior", "style"]
}
```

输出：

```json
{
  "avatar_id": "avatar_001",
  "avatar_version": 1,
  "identity": {},
  "personality": {},
  "expertise": [],
  "interests": [],
  "opinions": [],
  "behavior_memories": [],
  "style": {},
  "policy": {}
}
```

`growth`、`sources`、修改历史和内部审计字段不进入模型上下文，除非某个 Agent 管理功能明确需要它们。

### 7. 检索用户记忆

能力名：`search_avatar_memories`

输入：

```json
{
  "request_id": "req_005",
  "avatar_id": "avatar_001",
  "query": "我怎么看远程办公",
  "memory_types": ["opinion", "behavior", "expertise", "interest"],
  "allowed_depths": ["deep", "middle", "shallow"],
  "allowed_status": ["confirmed", "unconfirmed"],
  "top_k": 8
}
```

输出：

```json
{
  "items": [
    {
      "memory_id": "memory_001",
      "type": "opinion",
      "depth": "middle",
      "content": "用户支持有条件的混合办公。",
      "confidence": 0.84,
      "status": "confirmed",
      "source_refs": ["ev_002"],
      "valid_from": "2024-03-15",
      "share": false
    }
  ]
}
```

后端必须过滤 `rejected`、`deleted`、撤销来源和无权限内容。`unconfirmed` 可以返回，但 Agent 必须降低确定性，不能把它说成用户明确事实。

### 8. 获取证据原文

能力名：`get_evidences`

输入：

```json
{
  "request_id": "req_006",
  "avatar_id": "avatar_001",
  "evidence_refs": ["ev_002"]
}
```

输出：

```json
{
  "items": [
    {
      "evidence_id": "ev_002",
      "document_id": "doc_002",
      "quote": "成熟研发团队可以远程，但初创团队早期需要更多线下沟通。",
      "source_url": "https://www.zhihu.com/...",
      "created_at": "2024-03-15T10:00:00Z",
      "privacy": "private",
      "share": false
    }
  ]
}
```

Agent 只能引用实际返回的证据，不能自行编造引用 ID 或原文。

### 9. 回传 Agent 事件和提案

能力名：`emit_agent_event`

Agent 返回给传统后端，不直接写画像：

```json
{
  "event_id": "event_001",
  "event_type": "memory_proposal|evidence_update|personality_change_proposal|question_proposal",
  "avatar_id": "avatar_001",
  "source_refs": ["conversation_turn_004"],
  "payload": {},
  "requires_user_confirmation": true
}
```

传统后端负责保存、审核、让用户确认、正式落库和生成新版本。

## 前端 POST 到 Agent 的路由方式

前端调用传统后端业务接口，例如：

```http
POST /api/v1/avatar/answer
```

传统后端执行：

```text
1. 从 HttpOnly Cookie 得到当前 user_id
2. 校验 avatar_id、版本、权限和场景
3. 调用 Agent Runtime
4. Agent Runtime 通过 BackendDataProvider 调用上述数据能力
5. Agent 返回 answer、引用、置信度和事件
6. 传统后端保存运行记录并返回前端
```

前端不能直接调用：

```text
/internal/agent/*
BackendDataProvider
知乎 OAuth 接口
数据库、对象存储或向量库
```

## 错误语义

数据能力统一返回以下错误：

```text
NOT_AUTHENTICATED       未登录
POLICY_DENIED           用途或权限不允许
TOKEN_EXPIRED           知乎 Token 过期
SOURCE_REVOKED          来源已撤销
NOT_FOUND               数据不存在
RATE_LIMITED            知乎或后端限流
UPSTREAM_UNAVAILABLE    知乎服务暂时不可用
INVALID_REQUEST         参数或版本错误
```

`POLICY_DENIED`、`SOURCE_REVOKED` 和 `TOKEN_EXPIRED` 不应由 Agent 自动重试。`UPSTREAM_UNAVAILABLE` 可以由传统后端按幂等键重试。

## Agent 开发者的实现顺序

1. 先实现 `BackendDataProvider` 接口和 Mock 数据源。
2. 使用 `get_avatar_snapshot`、`search_avatar_memories`、`get_evidences` 完成回答链路。
3. 再接入 `list_zhihu_contents` 进行初始化画像抽取。
4. 将 `emit_agent_event` 接入传统后端的事件入口。
5. 最后替换 Mock 为传统后端内部适配器或 HTTP/RPC 适配器。

Agent 代码不应依赖 `backend/app/imports` 的具体文件路径。只依赖本文定义的能力名、输入输出和错误语义，这样传统后端可以替换内部实现而不影响 Agent。
