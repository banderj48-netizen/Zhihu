# 数字分身初始化接口说明

本文对应 `backend/agent/runtime/api.py` 的正式初始化接口。所有请求都应携带登录后的 `twinloop_session` Cookie；服务端会从 Cookie 解析用户，不能由前端伪造用户 ID。

## 流程总览

```text
知乎 OAuth 登录
  -> POST /v1/twin/initializations
  -> personality（性格）
  -> domains（兴趣/专长）
  -> opinion-questions -> opinion-answers（观点）
  -> social-questions -> social-answers（社交行为）
  -> complete（创建数字分身）
```

## 1. 创建或恢复初始化会话

```http
POST /v1/twin/initializations
Content-Type: application/json
Cookie: twinloop_session=...
```

```json
{"import_job_id": "job_xxx"}
```

`import_job_id` 可选。接口写入 PostgreSQL 的 `avatar_initialization_sessions`，同一用户重复调用会恢复已有会话。

## 2. 查询会话

```http
GET /v1/twin/initializations/{session_id}
Cookie: twinloop_session=...
```

返回 `status`、`current_step`、`input_data`、`generated_profile` 等字段。

## 3. 性格测评

获取题目：

```http
GET /v1/personality/questions
```

保存到初始化会话：

```http
POST /v1/twin/initializations/{session_id}/personality
Content-Type: application/json
```

```json
{"data":{"answers":{"E01":4,"A01":3},"notes":"可选"}}
```

也可使用兼容接口 `POST /v1/personality/assessments`，但正式初始化推荐上面的会话步骤接口。

## 4. 兴趣和专长

查询领域目录：`GET /v1/domains`

提交：

```http
POST /v1/twin/initializations/{session_id}/domains
```

```json
{"data":{"interests":[{"domain_id":"人工智能","level":"interested"}],"expertise":[{"domain_id":"软件工程","level":"熟悉"}]}}
```

## 5. 观点题

生成题目：

```http
POST /v1/twin/initializations/{session_id}/opinion-questions
```

```json
{"count":5,"domain_ids":["人工智能"]}
```

提交答案：

```http
POST /v1/twin/initializations/{session_id}/opinion-answers
```

```json
{"data":{"answers":[{"topic":"人工智能","selected_option_id":"opt_a","custom_text":""}]}}
```

题目优先由 LLM 结合知乎素材生成，LLM 不可用时回退模板题库。

## 6. 社交情景题

生成题目：

```http
POST /v1/twin/initializations/{session_id}/social-questions
```

```json
{"count":5}
```

提交答案：

```http
POST /v1/twin/initializations/{session_id}/social-answers
```

```json
{"data":{"answers":[{"topic":"陌生人交流","selected_option_id":"opt_a","elapsed_seconds":8}]}}
```

社交题有 `time_limit_seconds`，当前实现对超过 13 秒的行为记忆不写入。

## 7. 完成初始化

```http
POST /v1/twin/initializations/{session_id}/complete
Content-Type: application/json
Cookie: twinloop_session=...
```

```json
{"identity":{"display_name":"林同学","summary":"关注技术和社会问题","occupation":"学生","location":"北京"}}
```

完成时会在 PostgreSQL 创建或激活：

```text
user_avatars（一个用户唯一一条）
avatar_versions
avatar_identity
avatar_personality
avatar_styles
avatar_policies
avatar_memory_rules
source_documents
avatar_memories
```

## 状态与错误

典型状态：`importing`、`personality_pending`、`domain_pending`、`opinion_questions_pending`、`generating_profile`、`review`、`completed`、`failed`。

- `401`：没有有效登录 Cookie
- `404`：会话不存在或不属于当前用户
- `400`：步骤数据或完成参数无效
- `503`：数据库或初始化服务暂不可用

## 本地测试

```powershell
curl.exe -b cookies.txt -X POST http://127.0.0.1:8000/v1/twin/initializations -H "Content-Type: application/json" -d "{}"
```

所有步骤都应复用同一个 `session_id` 和 `cookies.txt`。完成后可查询数据库：

```sql
SELECT * FROM avatar_initialization_sessions ORDER BY created_at DESC;
SELECT id, user_id, current_version_id, status FROM user_avatars;
```
