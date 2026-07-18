# 多智能体对话系统

基于 LangGraph 的多智能体 AI 对话系统，支持联网搜索、图片识别、文档检索、长期记忆、流式响应和 JWT 认证。

## 功能特性

### 核心能力

- **联网搜索**：通过 Tavily API 实时搜索互联网信息
- **图片识别**：使用本地 Ollama 多模态模型（qwen3-vl:8b）识别图片内容
- **文档检索（RAG）**：上传文档到 ChromaDB 向量库，基于文档内容进行问答
- **长期记忆**：自动存储对话历史，支持跨会话记忆检索
- **流式响应**：SSE（Server-Sent Events）实时推送思考过程和回答
- **思考过程可视化**：类似豆包专家版，显示 AI 的思考过程和最终回答
- **JWT 认证**：用户注册、登录、会话管理
- **Prometheus 监控**：内置业务指标和性能监控

### 智能路由

系统通过调度主管自动判断问题类型，路由到不同的处理流程：

- **SEARCH**：需要实时信息（天气、新闻、最新数据）→ 联网搜索
- **RAG**：需要文档内容（用户上传的资料）→ 文档检索
- **DIRECT**：常识、计算、翻译等 → 直接回答

### 工作流架构

```
START → preprocess(预处理) → supervisor(调度主管) → [search|rag|direct] → answer(回答) → store_memory(记忆存储) → END
```

6 个核心节点：

1. **preprocess**：图片识别、长期记忆检索、RAG 上下文准备
2. **supervisor**：调度主管，判断路由（SEARCH/RAG/DIRECT）
3. **search**：联网搜索（Tavily API）
4. **rag**：文档检索（ChromaDB）
5. **answer**：生成回答（DeepSeek API）
6. **store_memory**：存储对话到长期记忆

## 技术栈

### 后端

- **FastAPI**：异步 Web 框架
- **LangGraph**：多智能体编排框架
- **LangChain**：LLM 应用开发工具链
- **DeepSeek API**：主力 LLM（OpenAI 兼容接口）
- **Ollama**：本地模型服务（视觉识别 + 嵌入）
- **ChromaDB**：向量数据库（RAG + 长期记忆）
- **Tavily**：联网搜索 API
- **SQLite**：用户数据和会话存储
- **JWT**：认证授权

### 前端

- **React**：UI 框架
- **TypeScript**：类型安全
- **Vite**：构建工具
- **Nginx**：生产环境静态文件托管

### 部署

- **Docker**：容器化
- **Docker Compose**：多服务编排

## 快速开始

### 环境要求

- Python 3.11+
- Node.js 20+（前端开发）
- Ollama（本地模型服务）
- DeepSeek API Key
- Tavily API Key

### 1. 克隆项目

```bash
git clone https://github.com/LKF123456-sys/pythonagent.git
cd pythonagent/multi_agent_system
```

### 2. 安装依赖

```bash
# 安装 Python 依赖
pip install -r requirements.txt

# 安装前端依赖（可选）
cd frontend
npm install
cd ..
```

### 3. 配置环境变量

复制 `.env.example` 为 `.env` 并填写配置：

```bash
# DeepSeek API（必需）
OPENAI_API_KEY=your-deepseek-api-key
OPENAI_BASE_URL=https://api.deepseek.com
MODEL_NAME=deepseek-chat

# Tavily 联网搜索（必需）
TAVILY_API_KEY=your-tavily-api-key

# 本地 Ollama 模型
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen2.5:7b
OLLAMA_VISION_MODEL=qwen3-vl:8b
OLLAMA_EMBED_MODEL=nomic-embed-text

# JWT 认证（生产环境请替换为强随机密钥）
JWT_SECRET_KEY=change-me-to-a-strong-random-secret-in-production
JWT_ALGORITHM=HS256
JWT_EXPIRE_MINUTES=1440

# 数据库路径
DATABASE_PATH=./data/app.db
CHROMA_DB_PATH=./data/chroma_db

# 日志配置
LOG_LEVEL=INFO
LOG_FILE=logs/app.log

# CORS 配置
CORS_ORIGINS=http://localhost:5173,http://localhost:3000,http://127.0.0.1:5173
```

### 4. 启动 Ollama 服务

```bash
# 启动 Ollama 服务
ollama serve

# 拉取所需模型（首次运行）
ollama pull qwen3-vl:8b      # 视觉识别模型
ollama pull qwen2.5:7b       # 文本模型（可选）
ollama pull nomic-embed-text # 嵌入模型（RAG + 长期记忆）
```

### 5. 启动后端服务

```bash
# 开发模式
uvicorn web_app:app --host 127.0.0.1 --port 8000 --reload

# 生产模式
uvicorn web_app:app --host 0.0.0.0 --port 8000 --workers 4
```

访问：
- **Web 界面**：http://127.0.0.1:8000
- **API 文档**：http://127.0.0.1:8000/docs
- **监控指标**：http://127.0.0.1:8000/metrics

### 6. 启动前端（可选）

```bash
cd frontend
npm run dev
```

访问：http://localhost:5173

## Docker 部署

### 使用 Docker Compose（推荐）

```bash
# 构建并启动所有服务
docker-compose up -d

# 查看日志
docker-compose logs -f

# 停止服务
docker-compose down
```

服务地址：
- **后端 API**：http://localhost:8000
- **前端界面**：http://localhost:3000

### 单独构建镜像

```bash
# 构建后端镜像
docker build -t agent-backend --target backend .

# 构建前端镜像
docker build -t agent-frontend ./frontend

# 运行容器
docker run -d -p 8000:8000 --env-file .env -v ./data:/app/data agent-backend
docker run -d -p 3000:80 agent-frontend
```

## 项目结构

```
multi_agent_system/
├── agents.py              # 智能体定义（调度主管、搜索、视觉、回答）
├── graph.py               # LangGraph 工作流编排
├── web_app.py             # FastAPI 后端主程序
├── auth.py                # JWT 认证模块
├── database.py            # SQLite 数据库操作
├── memory.py              # 长期记忆和 RAG 管理
├── config.py              # 配置管理
├── logger.py              # 日志模块
├── main.py                # 命令行入口（可选）
├── requirements.txt       # Python 依赖
├── .env                   # 环境变量配置
├── Dockerfile             # 后端 Docker 配置
├── docker-compose.yml     # Docker Compose 编排
├── API.md                 # API 文档
├── README.md              # 项目文档（本文件）
├── templates/
│   └── index.html         # 内置 Web 界面
├── frontend/              # React 前端项目
│   ├── src/
│   │   ├── api/           # API 客户端
│   │   ├── components/    # UI 组件
│   │   ├── pages/         # 页面
│   │   ├── store/         # 状态管理
│   │   └── types.ts       # TypeScript 类型定义
│   ├── package.json
│   └── vite.config.ts
├── tests/
│   └── test_app.py        # 单元测试
├── data/                  # 数据目录（自动创建）
│   ├── app.db             # SQLite 数据库
│   └── chroma_db/         # ChromaDB 向量库
├── logs/                  # 日志目录（自动创建）
│   └── app.log
└── uploads/               # 上传文件目录（自动创建）
```

## API 概览

详细 API 文档请查看 [API.md](./API.md) 或访问 http://127.0.0.1:8000/docs

### 认证接口

- `POST /api/auth/register` - 用户注册
- `POST /api/auth/login` - 用户登录
- `GET /api/auth/me` - 获取当前用户信息

### 会话接口

- `GET /api/session` - 获取新会话 ID
- `POST /api/session/new` - 创建新会话
- `GET /api/conversations` - 获取历史会话列表
- `GET /api/conversations/{id}/messages` - 获取会话消息
- `DELETE /api/conversations/{id}` - 删除会话

### 聊天接口

- `POST /api/chat` - 非流式聊天
- `POST /api/chat/stream` - SSE 流式聊天（推荐）

### 上传接口

- `POST /api/upload/image` - 上传图片
- `POST /api/upload/document` - 上传文档到 RAG

### 文档接口

- `GET /api/documents` - 获取文档列表
- `DELETE /api/documents/{filename}` - 删除文档

### 系统接口

- `GET /api/health` - 健康检查
- `GET /metrics` - Prometheus 监控指标

## 使用示例

### 注册并登录

```bash
# 注册
curl -X POST http://127.0.0.1:8000/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username": "demo", "password": "demo123"}'

# 登录（获取 token）
curl -X POST http://127.0.0.1:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "demo", "password": "demo123"}'
```

### 流式聊天

```bash
curl -X POST http://127.0.0.1:8000/api/chat/stream \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "question": "今天北京天气怎么样？",
    "session_id": "test-session-1",
    "is_first_turn": true
  }'
```

### 上传图片并识别

```bash
# 1. 上传图片
curl -X POST http://127.0.0.1:8000/api/upload/image \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -F "image=@screenshot.png"

# 2. 使用返回的 filename 进行聊天
curl -X POST http://127.0.0.1:8000/api/chat/stream \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "question": "这张图片里有什么？",
    "session_id": "test-session-2",
    "image_filename": "screenshot_1234567890.png",
    "is_first_turn": true
  }'
```

### 上传文档到 RAG

```bash
# 1. 上传文档
curl -X POST http://127.0.0.1:8000/api/upload/document \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -F "document=@manual.pdf"

# 2. 基于文档内容问答
curl -X POST http://127.0.0.1:8000/api/chat/stream \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "question": "根据文档，如何配置系统？",
    "session_id": "test-session-3",
    "is_first_turn": true
  }'
```

## 配置说明

### 模型配置

- **主力 LLM**：DeepSeek API（`deepseek-chat`），用于调度主管和回答生成
- **视觉模型**：Ollama `qwen3-vl:8b`，用于图片识别
- **嵌入模型**：Ollama `nomic-embed-text`，用于 RAG 和长期记忆的向量化

### 记忆配置

- **短期记忆**：保留最近 10 轮对话（`MAX_HISTORY_TURNS`）
- **长期记忆**：每次检索最多召回 5 条（`LONG_TERM_TOP_K`）

### 上传限制

- **图片**：png, jpg, jpeg, gif, bmp, webp
- **文档**：txt, md, csv, json, pdf, html, py, java, js, ts
- **最大文件大小**：20MB

## 监控指标

系统内置 Prometheus 监控指标：

- `agent_requests_total`：智能体路由决策总数（按类型）
- `llm_response_duration_seconds`：LLM 调用耗时（按智能体）
- `rag_chunks_stored_total`：RAG 文档切片存储总数

访问 http://127.0.0.1:8000/metrics 获取指标数据。

## 测试

```bash
# 运行单元测试
pytest tests/

# 运行测试并显示覆盖率
pytest tests/ --cov=. --cov-report=term-missing
```

## 常见问题

### Q: Ollama 服务无法连接？

A: 确保 Ollama 服务已启动：
```bash
ollama serve
```

### Q: 图片识别失败？

A: 检查是否已拉取视觉模型：
```bash
ollama pull qwen3-vl:8b
```

### Q: RAG 检索不到内容？

A: 确保已上传文档并等待嵌入完成。检查 ChromaDB 路径是否正确。

### Q: 如何更换 LLM 模型？

A: 修改 `.env` 中的 `MODEL_NAME` 和 `OPENAI_BASE_URL`，支持任何 OpenAI 兼容接口。

## 许可证

MIT License

## 贡献

欢迎提交 Issue 和 Pull Request！

## 联系方式

- GitHub: https://github.com/LKF123456-sys/pythonagent
- 问题反馈: 请在 GitHub Issues 中提交

---

**注意**：本项目仅供学习和研究使用，请遵守相关 API 服务的使用条款。
