# API 文档

本文档描述多智能体系统 FastAPI 服务的 HTTP API。接口版本为 `2.0.0`。

## 服务地址

本地开发默认地址：

```text
http://127.0.0.1:8000
```

服务启动后还可访问自动生成的接口文档：

- Swagger UI：`http://127.0.0.1:8000/docs`
- ReDoc：`http://127.0.0.1:8000/redoc`
- OpenAPI JSON：`http://127.0.0.1:8000/openapi.json`

除注册、登录、健康检查和前端首页外，其余接口均要求 JWT Bearer Token。

## 认证

调用受保护接口时添加请求头：

```http
Authorization: Bearer <access_token>
```

### 注册用户

`POST /api/auth/register`

请求体：

```json
{
  "username": "demo_user",
  "password": "example-password"
}
```

约束：

- 用户名长度为 2 至 50 个字符。
- 密码长度不少于 6 个字符。
- 用户名不能重复。

成功响应：

```json
{
  "access_token": "<jwt-token>",
  "token_type": "bearer",
  "user_id": 1,
  "username": "demo_user"
}
```

可能的错误：

- `400`：用户名或密码不符合要求。
- `409`：用户名已存在。
- `422`：请求体格式错误或缺少字段。

### 用户登录

`POST /api/auth/login`

请求体：

```json
{
  "username": "demo_user",
  "password": "example-password"
}
```

成功响应格式与注册接口相同。

可能的错误：

- `401`：用户名或密码错误。
- `403`：账户已被禁用。

### 获取当前用户

`GET /api/auth/me`

需要认证。

成功响应：

```json
{
  "user_id": 1,
  "username": "demo_user",
  "created_at": "2026-07-18T10:00:00"
}
```

## 会话

### 获取新会话标识

`GET /api/session`

需要认证。每次调用都会生成新的 8 位 `session_id`。

成功响应：

```json
{
  "session_id": "a1b2c3d4",
  "is_new": true
}
```

### 创建新会话标识

`POST /api/session/new`

需要认证。

成功响应：

```json
{
  "session_id": "a1b2c3d4"
}
```

### 获取历史会话

`GET /api/conversations`

需要认证。结果按最后更新时间倒序排列。

成功响应：

```json
{
  "conversations": [
    {
      "session_id": "a1b2c3d4",
      "title": "介绍一下 LangGraph",
      "created_at": "2026-07-18T10:00:00",
      "updated_at": "2026-07-18T10:02:00"
    }
  ]
}
```

### 获取会话消息

`GET /api/conversations/{conv_id}/messages`

需要认证。最多返回 100 条消息，按创建时间正序排列。

成功响应：

```json
{
  "messages": [
    {
      "role": "user",
      "content": "你好",
      "created_at": "2026-07-18T10:00:00"
    },
    {
      "role": "assistant",
      "content": "你好，有什么可以帮你？",
      "created_at": "2026-07-18T10:00:02"
    }
  ]
}
```

### 删除会话

`DELETE /api/conversations/{conv_id}`

需要认证。会同时删除该会话的消息。

成功响应：

```json
{
  "success": true
}
```

## 聊天

聊天请求体结构：

```json
{
  "question": "介绍一下 LangGraph",
  "session_id": "a1b2c3d4",
  "image_filename": "example_1784300000.png",
  "is_first_turn": true
}
```

字段说明：

| 字段 | 类型 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- | --- |
| `question` | string | 是 | 无 | 用户问题，去除空白后不能为空。 |
| `session_id` | string 或 null | 否 | 自动生成 | LangGraph Checkpointer 的线程标识。后续对话应复用同一值。 |
| `image_filename` | string 或 null | 否 | `""` | 图片上传接口返回的文件名。文件不存在时按纯文本请求处理。 |
| `is_first_turn` | boolean | 否 | `true` | 首轮设为 `true`，后续对话设为 `false`。 |

### 非流式聊天

`POST /api/chat`

需要认证。

成功响应：

```json
{
  "answer": "LangGraph 是用于构建有状态智能体工作流的框架。",
  "session_id": "a1b2c3d4",
  "image_path": "",
  "error": null
}
```

可能的错误：

- `400`：问题为空。
- `500`：智能体执行失败。

### SSE 流式聊天

`POST /api/chat/stream`

需要认证。请求体与非流式聊天相同，响应类型为 `text/event-stream`。

事件采用以下格式：

```text
data: {"type":"status","node":"supervisor"}

data: {"type":"token","content":"你好"}

data: {"type":"done"}

```

事件类型：

| `type` | 字段 | 说明 |
| --- | --- | --- |
| `status` | `node` | 当前执行节点，例如 `preprocess`、`supervisor`、`search`、`answer`。 |
| `token` | `content` | 回答文本增量。客户端应按顺序拼接。 |
| `done` | 无 | 流正常结束。 |
| `error` | `error` | 流执行失败，字段中包含错误描述。 |

浏览器原生 `EventSource` 只能发送 GET 请求，此接口是 POST，因此前端应使用 `fetch` 读取响应流。

## 图片上传与识别

图片识别采用两步流程：先上传图片，再把返回的 `filename` 作为 `image_filename` 调用聊天接口。

### 上传图片

`POST /api/upload/image`

需要认证。请求内容类型为 `multipart/form-data`，表单字段名为 `image`。

支持扩展名：`png`、`jpg`、`jpeg`、`gif`、`bmp`、`webp`。

成功响应：

```json
{
  "filename": "screen_1784300000.png",
  "path": "./uploads/screen_1784300000.png",
  "error": null
}
```

随后调用聊天接口：

```json
{
  "question": "请描述这张图片",
  "session_id": "a1b2c3d4",
  "image_filename": "screen_1784300000.png",
  "is_first_turn": true
}
```

## RAG 文档

### 上传文档

`POST /api/upload/document`

需要认证。请求内容类型为 `multipart/form-data`，表单字段名为 `document`。

支持扩展名：`txt`、`md`、`csv`、`json`、`pdf`、`html`、`py`、`java`、`js`、`ts`。

成功响应：

```json
{
  "filename": "guide.md",
  "chunks": 12,
  "error": null
}
```

`chunks` 为写入向量库的切片数量。如果嵌入模型或 ChromaDB 不可用，当前实现可能返回 `0`。

### 获取文档列表

`GET /api/documents`

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

`DELETE /api/documents/{filename}`

需要认证。

成功响应：

```json
{
  "success": true
}
```

## 系统接口

### 健康检查

`GET /api/health`

无需认证。

成功响应：

```json
{
  "status": "ok",
  "version": "2.0.0"
}
```

### Prometheus 指标

`GET /metrics`

安装 `prometheus-fastapi-instrumentator` 后可用。该端点用于输出 Prometheus 文本格式指标。

## 调用示例

以下 PowerShell 示例使用变量保存 Token，不包含任何真实凭据。

### 注册并发送消息

```powershell
$baseUrl = "http://127.0.0.1:8000"

$registerBody = @{
    username = "demo_user"
    password = "example-password"
} | ConvertTo-Json

$auth = Invoke-RestMethod `
    -Uri "$baseUrl/api/auth/register" `
    -Method Post `
    -ContentType "application/json" `
    -Body $registerBody

$headers = @{ Authorization = "Bearer $($auth.access_token)" }

$chatBody = @{
    question = "介绍一下 LangGraph"
    session_id = $null
    image_filename = ""
    is_first_turn = $true
} | ConvertTo-Json

Invoke-RestMethod `
    -Uri "$baseUrl/api/chat" `
    -Method Post `
    -Headers $headers `
    -ContentType "application/json" `
    -Body $chatBody
```

### 使用 curl 上传图片

```bash
curl -X POST "http://127.0.0.1:8000/api/upload/image" \
  -H "Authorization: Bearer <access_token>" \
  -F "image=@screen.png"
```

### 使用 Python 调用流式聊天

```python
import json
import requests

base_url = "http://127.0.0.1:8000"
token = "<access_token>"

payload = {
    "question": "介绍一下 LangGraph",
    "session_id": None,
    "image_filename": "",
    "is_first_turn": True,
}

with requests.post(
    f"{base_url}/api/chat/stream",
    headers={"Authorization": f"Bearer {token}"},
    json=payload,
    stream=True,
    timeout=120,
) as response:
    response.raise_for_status()
    for line in response.iter_lines(decode_unicode=True):
        if not line or not line.startswith("data: "):
            continue
        event = json.loads(line[6:])
        if event["type"] == "token":
            print(event["content"], end="", flush=True)
        elif event["type"] == "error":
            raise RuntimeError(event["error"])
        elif event["type"] == "done":
            print()
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
| --- | --- |
| `200` | 请求成功。 |
| `400` | 参数或文件内容不符合要求。 |
| `401` | 未提供 Token，或 Token 无效、过期。 |
| `403` | 当前账户被禁用。 |
| `409` | 注册用户名已存在。 |
| `422` | JSON 或表单字段校验失败。 |
| `500` | 服务端执行失败。 |
