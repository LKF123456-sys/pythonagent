# API 文档

本文档描述多智能体系统 FastAPI 服务的 HTTP API 与 WebSocket API。当前所有业务接口统一使用 `/api/v1` 版本前缀。

## 服务地址

本地开发默认地址：

```text
http://127.0.0.1:8000
```

自动生成文档：

- Swagger UI：`http://127.0.0.1:8000/docs`
- ReDoc：`http://127.0.0.1:8000/redoc`
- OpenAPI JSON：`http://127.0.0.1:8000/openapi.json`
- Prometheus 指标：`http://127.0.0.1:8000/metrics`

除注册、登录、健康检查、Prometheus 指标和前端静态页面外，其余接口均要求 JWT Bearer Token。

## 认证方式

受保护 HTTP 接口使用请求头：

```http
Authorization: Bearer <access_token>
```

WebSocket 接口通过查询参数传递 Token：

```text
?token=<access_token>
```

## 认证接口

### 注册用户

`POST /api/v1/auth/register`

请求体：

```json
{
  "username": "demo_user",
  "password": "example-password"
}
```

成功响应：

```json
{
  "access_token": "<jwt-access-token>",
  "refresh_token": "<jwt-refresh-token>",
  "token_type": "bearer",
  "user_id": 1,
  "username": "demo_user"
}
```

可能错误：

- `400`：用户名或密码不符合要求。
- `409`：用户名已存在。
- `422`：请求体格式错误或缺少字段。

### 用户登录

`POST /api/v1/auth/login`

请求体：

```json
{
  "username": "demo_user",
  "password": "example-password"
}
```

成功响应格式与注册接口一致。

可能错误：

- `401`：用户名或密码错误。
- `403`：账户已被禁用。

### 刷新 Token

`POST /api/v1/auth/refresh`

请求体：

```json
{
  "refresh_token": "<jwt-refresh-token>"
}
```

成功响应格式与登录接口一致。

### 登出

`POST /api/v1/auth/logout`

请求体：

```json
{
  "refresh_token": "<jwt-refresh-token>"
}
```

成功响应：`204 No Content`。

### 获取当前用户

`GET /api/v1/auth/me`

需要认证。

成功响应：

```json
{
  "user_id": 1,
  "username": "demo_user",
  "is_admin": false,
  "created_at": "2026-07-18T10:00:00"
}
```

## 通用聊天接口

### WebSocket 流式聊天

`WS /api/v1/ws/chat/{session_id}?token=<access_token>`

客户端发送消息：

```json
{
  "question": "介绍一下 LangGraph",
  "image_filename": null,
  "is_first_turn": true
}
```

服务端事件类型：

| 类型 | 字段 | 说明 |
|------|------|------|
| `status` | `node` / `content` | 当前执行节点或状态提示 |
| `token` | `content` | 回答文本增量，客户端按顺序拼接 |
| `thought` | `content` | 思考过程内容 |
| `tool` | `content` | 工具调用或搜索/RAG提示 |
| `done` | `answer` / `token_count` | 对话完成事件 |
| `error` | `content` | 执行失败描述 |

示例事件：

```json
{"type":"status","node":"supervisor","content":"调度主管分析中"}
```

```json
{"type":"token","content":"你好"}
```

```json
{"type":"done","answer":"你好，有什么可以帮你？","token_count":18}
```

### 非流式聊天

`POST /api/v1/chat`

需要认证。

请求体：

```json
{
  "question": "介绍一下 LangGraph",
  "session_id": "a1b2c3d4",
  "image_filename": null,
  "is_first_turn": true
}
```

成功响应：

```json
{
  "answer": "LangGraph 是用于构建有状态智能体工作流的框架。",
  "session_id": "a1b2c3d4",
  "token_count": 128,
  "error": null
}
```

### 上传聊天图片

`POST /api/v1/chat/upload-image`

需要认证。请求内容类型为 `multipart/form-data`，表单字段名为 `file`。

成功响应：

```json
{
  "filename": "screen_1784300000.png"
}
```

随后在聊天请求中传入：

```json
{
  "question": "请描述这张图片",
  "session_id": "a1b2c3d4",
  "image_filename": "screen_1784300000.png"
}
```

## 会话管理接口

### 获取会话列表

`GET /api/v1/conversations?conv_type=general`

需要认证。

查询参数：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `conv_type` | string | `general` | 会话类型：`general` 或 `mfg` |

成功响应：

```json
{
  "conversations": [
    {
      "session_id": "a1b2c3d4",
      "title": "介绍一下 LangGraph",
      "conv_type": "general",
      "created_at": "2026-07-18T10:00:00",
      "updated_at": "2026-07-18T10:02:00"
    }
  ]
}
```

### 获取会话消息

`GET /api/v1/conversations/{session_id}/messages`

需要认证。

成功响应：

```json
{
  "messages": [
    {
      "role": "user",
      "content": "你好",
      "image_filename": null,
      "created_at": "2026-07-18T10:00:00"
    },
    {
      "role": "assistant",
      "content": "你好，有什么可以帮你？",
      "token_count": 18,
      "created_at": "2026-07-18T10:00:02"
    }
  ]
}
```

### 重命名会话

`PATCH /api/v1/conversations/{session_id}`

请求体：

```json
{
  "title": "新的会话标题"
}
```

成功响应：`204 No Content`。

### 删除会话

`DELETE /api/v1/conversations/{session_id}`

成功响应：`204 No Content`。

### 导出会话

`GET /api/v1/conversations/{session_id}/export?format=markdown`

查询参数：

| 参数 | 类型 | 说明 |
|------|------|------|
| `format` | string | `markdown` 或 `json` |

### Token 统计

`GET /api/v1/stats/tokens?days=30`

需要认证。

## RAG 文档接口

### 上传文档

`POST /api/v1/documents/upload`

需要认证。请求内容类型为 `multipart/form-data`，表单字段名为 `file`。

支持扩展名包括：`txt`、`md`、`csv`、`json`、`pdf`、`docx`、`html`、`py`、`java`、`js`、`ts`。

成功响应：

```json
{
  "filename": "guide.md",
  "chunks": 12
}
```

### 获取文档列表

`GET /api/v1/documents`

需要认证。

成功响应：

```json
{
  "documents": [
    {
      "filename": "guide.md",
      "chunks": 12,
      "timestamp": "2026-07-18T10:00:00"
    }
  ]
}
```

### 删除文档

`DELETE /api/v1/documents/{filename}`

需要认证。

成功响应：`204 No Content`。

## 工业智造接口

### 工业 WebSocket 聊天

`WS /api/v1/ws/manufacturing/{session_id}?token=<access_token>`

客户端发送消息格式与通用聊天一致。

### 查询故障码

`GET /api/v1/mfg/fault-codes?code=E001`

需要认证。

### 查询设备信息

`GET /api/v1/mfg/equipment?equipment_id=EQ-001`

需要认证。

### 上传工业图片

`POST /api/v1/mfg/upload-image`

需要认证。请求内容类型为 `multipart/form-data`，表单字段名为 `file`。

### 上传工业文档

`POST /api/v1/mfg/documents/upload`

需要认证。请求内容类型为 `multipart/form-data`，表单字段名为 `file`。

### 获取工业文档列表

`GET /api/v1/mfg/documents`

需要认证。

### 删除工业文档

`DELETE /api/v1/mfg/documents/{filename}`

需要认证。成功响应：`204 No Content`。

### 访问上传文件

`GET /api/v1/uploads/{filename}?token=<access_token>`

该接口用于前端展示已上传图片。

## Human-in-the-loop 人工审批接口

当 `HITL_ENABLED=true` 且用户问题触发敏感关键词时，LangGraph 工作流会在 `human_review` 节点 interrupt 暂停。

### 批准请求

`POST /api/v1/review/approve`

请求体：

```json
{
  "thread_id": "a1b2c3d4",
  "action": "approved"
}
```

成功响应：

```json
{
  "success": true,
  "message": "审批已通过，请求继续执行"
}
```

### 拒绝请求

`POST /api/v1/review/reject`

请求体：

```json
{
  "thread_id": "a1b2c3d4",
  "action": "rejected"
}
```

成功响应：

```json
{
  "success": true,
  "message": "审批已拒绝，请求已终止"
}
```

## 管理接口

以下接口需要管理员权限。

### 获取用户列表

`GET /api/v1/admin/users`

### 更新用户状态

`PATCH /api/v1/admin/users/{user_id}`

请求体：

```json
{
  "is_active": true
}
```

### 获取系统统计

`GET /api/v1/admin/stats`

## 系统接口

### 基础健康检查

`GET /api/v1/health`

无需认证。

成功响应：

```json
{
  "status": "ok",
  "version": "2.0.0"
}
```

### 深度健康检查

`GET /api/v1/health/deep`

检查数据库、Redis、熔断器和 LLM API 配置。

成功响应：

```json
{
  "healthy": true,
  "checks": {
    "database": {"status": "healthy", "latency_ms": 0},
    "redis": {"status": "healthy"},
    "circuit_breaker": {"state": "closed"},
    "llm_api": {"status": "configured"}
  }
}
```

如果任一关键依赖不健康，接口返回 `503`。

### Prometheus 指标

`GET /metrics`

返回 Prometheus 文本格式指标。

## 调用示例

### PowerShell 注册并发送非流式消息

```powershell
$baseUrl = "http://127.0.0.1:8000"

$registerBody = @{
    username = "demo_user"
    password = "example-password"
} | ConvertTo-Json

$auth = Invoke-RestMethod `
    -Uri "$baseUrl/api/v1/auth/register" `
    -Method Post `
    -ContentType "application/json" `
    -Body $registerBody

$headers = @{ Authorization = "Bearer $($auth.access_token)" }

$chatBody = @{
    question = "介绍一下 LangGraph"
    session_id = "demo-session"
    image_filename = $null
    is_first_turn = $true
} | ConvertTo-Json

Invoke-RestMethod `
    -Uri "$baseUrl/api/v1/chat" `
    -Method Post `
    -Headers $headers `
    -ContentType "application/json" `
    -Body $chatBody
```

### curl 上传文档

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/documents/upload" \
  -H "Authorization: Bearer <access_token>" \
  -F "file=@guide.md"
```

### Python WebSocket 调用示例

```python
import asyncio
import json
import websockets

async def main():
    token = "<access_token>"
    session_id = "demo-session"
    url = f"ws://127.0.0.1:8000/api/v1/ws/chat/{session_id}?token={token}"
    async with websockets.connect(url) as ws:
        await ws.send(json.dumps({"question": "你好", "is_first_turn": True}))
        async for message in ws:
            event = json.loads(message)
            print(event)
            if event.get("type") in {"done", "error"}:
                break

asyncio.run(main())
```

## 通用错误格式

FastAPI 主动抛出的请求错误通常采用：

```json
{
  "detail": "错误描述"
}
```

未捕获异常由全局异常处理器返回：

```json
{
  "error": "服务器内部错误",
  "detail": "具体错误信息"
}
```

常见状态码：

| 状态码 | 说明 |
|--------|------|
| `200` | 请求成功 |
| `201` | 资源创建成功 |
| `204` | 请求成功且无响应体 |
| `400` | 参数或文件内容不符合要求 |
| `401` | 未提供 Token，或 Token 无效、过期 |
| `403` | 权限不足或账户被禁用 |
| `409` | 资源冲突，例如用户名已存在 |
| `422` | JSON 或表单字段校验失败 |
| `500` | 服务端执行失败 |
| `503` | 深度健康检查发现关键依赖不可用 |
