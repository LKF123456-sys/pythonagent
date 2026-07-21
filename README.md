# 多智能体对话系统

基于 LangGraph 的生产就绪级多智能体 AI 对话系统，支持联网搜索、图片识别、RAG 文档检索、长期记忆、WebSocket 流式响应、JWT 认证和工业智造垂直领域。

## 功能特性

### 核心能力

- **联网搜索**：通过 Tavily API 实时搜索互联网信息
- **图片识别**：使用本地 Ollama 多模态模型（qwen3-vl:8b）识别图片内容
- **文档检索（RAG）**：上传文档到 pgvector 向量库，语义切片 + 向量相似度检索
- **长期记忆**：自动存储对话历史，支持跨会话记忆检索
- **WebSocket 流式响应**：双向实时通信，推送思考过程、节点状态和 token 流
- **LLM 容错**：重试（指数退避）+ 熔断器 + 降级模型 + 令牌预算（成本熔断）
- **JWT 双 Token 认证**：Access + Refresh Token，支持黑名单撤销
- **工业智造垂直域**：故障诊断、工艺优化、预测性维护、知识问答
- **Prometheus 监控**：内置业务指标和性能监控
- **OpenTelemetry 追踪**：可选启用分布式链路追踪

### 智能路由

系统通过调度主管（Supervisor）自动判断问题类型，路由到不同处理流程：

- **SEARCH**：需要实时信息（天气、新闻、最新数据）→ 联网搜索
- **RAG**：需要文档内容（用户上传的资料）→ 文档检索
- **DIRECT**：常识、计算、翻译等 → 直接回答

### 工作流架构（LangGraph astream_events 原生流式）

```
START → preprocess → supervisor → [search|rag|direct] → answer → store_memory → END
```

6 个核心节点：

1. **preprocess**：图片识别、长期记忆检索、RAG 上下文准备
2. **supervisor**：调度主管，判断路由（SEARCH/RAG/DIRECT）
3. **search**：联网搜索（Tavily API）
4. **rag**：文档检索（pgvector 向量相似度）
5. **answer**：生成回答（DeepSeek API，流式 token）
6. **store_memory**：存储对话到长期记忆向量库

### 双管线架构

```
通用管线：preprocess → supervisor → search/rag → answer → store_memory
工业管线：mfg_preprocess → mfg_supervisor → fault/process/predict/knowledge → mfg_answer → mfg_store
```

两条管线共享基础设施（Auth、WebSocket、Tracing、日志），业务逻辑完全隔离。

## 技术栈

### 后端

| 组件 | 技术 |
|------|------|
| Web 框架 | FastAPI（异步） |
| 多智能体编排 | LangGraph + LangChain |
| 主力 LLM | DeepSeek API（OpenAI 兼容） |
| 本地模型 | Ollama（视觉 + 嵌入） |
| 数据库 | PostgreSQL + asyncpg 连接池 |
| 向量检索 | pgvector（768 维，cosine 距离） |
| 联网搜索 | Tavily API |
| 认证 | JWT（python-jose + bcrypt） |
| 容错 | tenacity 重试 + 自研熔断器 |
| 可观测性 | OpenTelemetry + Prometheus |
| 日志 | 双输出（控制台 + 文件轮转）+ JSON 结构化 |
| 配置 | pydantic-settings 类型安全 |
| 频率限制 | slowapi |

### 前端

| 组件 | 技术 |
|------|------|
| UI 框架 | React 18 |
| 类型系统 | TypeScript |
| 构建工具 | Vite |
| 状态管理 | Zustand |
| 路由 | React Router |
| 动画 | Framer Motion |
| Markdown | react-markdown + remark-gfm |

### 部署

| 组件 | 技术 |
|------|------|
| 容器化 | 多阶段 Docker（Node 构建前端 → Python 后端内嵌） |
| 编排 | Docker Compose（app + PostgreSQL/pgvector） |
| CI/CD | GitHub Actions（ruff → mypy → pytest → 前端构建） |
| 代码质量 | ruff（lint）+ mypy（类型检查） |

## 快速开始

### 环境要求

- Python 3.11+
- Node.js 20+（前端开发）
- PostgreSQL 17 + pgvector 扩展（或使用 Docker Compose 自动提供）
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
# 安装 Python 依赖到 libs 目录
pip install -r requirements.txt --target libs

# 安装前端依赖（可选）
cd frontend
npm install
cd ..
```

### 3. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env，填入真实的 API Key 和数据库连接信息
```

关键配置项：
- `OPENAI_API_KEY`：DeepSeek API 密钥（必需）
- `TAVILY_API_KEY`：Tavily 搜索密钥（必需）
- `DATABASE_URL`：PostgreSQL 连接串
- `JWT_SECRET_KEY`：强随机密钥（≥32 字符，否则拒绝启动）

### 4. 启动数据库

```bash
# 使用 Docker Compose 启动 PostgreSQL + pgvector
docker compose up -d db
```

### 5. 启动 Ollama 并拉取模型

```bash
ollama serve
ollama pull qwen3-vl:8b       # 视觉识别
ollama pull nomic-embed-text   # 嵌入模型（RAG + 记忆）
```

### 6. 启动后端

```bash
# 开发模式（需设置 PYTHONPATH 指向 libs）
set PYTHONPATH=libs  # Windows
# export PYTHONPATH=libs  # Linux/Mac

uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

访问：
- **Web 界面**：http://localhost:8000（前端构建后内嵌）
- **API 文档**：http://localhost:8000/docs
- **监控指标**：http://localhost:8000/metrics

### 7. 启动前端开发服务器（可选）

```bash
cd frontend
npm run dev
```

访问：http://localhost:5173

## Docker 一键部署

```bash
# 构建并启动所有服务（app + PostgreSQL）
docker compose up -d --build

# 查看日志
docker compose logs -f app

# 停止服务
docker compose down
```

单容器同时提供 API / WebSocket / 前端页面（同源 8000 端口，无需反向代理）。

## 项目结构

```
multi_agent_system/
├── app/                        # 后端分层架构
│   ├── main.py                 # FastAPI 应用工厂 + lifespan
│   ├── agents/                 # 多智能体编排
│   │   ├── graph.py            # LangGraph 工作流（astream_events 流式）
│   │   ├── nodes.py            # 节点实现（preprocess/supervisor/search/rag/answer）
│   │   ├── llm.py              # LLM 创建（含容错包装）
│   │   ├── resilience.py       # 重试 + 熔断器 + 降级 + 令牌预算
│   │   ├── stream_parser.py    # 流式 token 解析器
│   │   ├── prompts.py          # 系统提示词
│   │   └── manufacturing/      # 工业智造垂直域
│   │       ├── graph.py        # 工业管线工作流
│   │       ├── nodes.py        # 工业节点（故障/工艺/预测/知识）
│   │       ├── knowledge.py    # 工业知识库
│   │       ├── tools.py        # 工业工具
│   │       └── prompts.py      # 工业提示词
│   ├── core/                   # 基础设施层
│   │   ├── config.py           # pydantic-settings 配置
│   │   ├── security.py         # JWT + bcrypt + 文件安全
│   │   ├── exceptions.py       # AppException 异常层次
│   │   ├── logging.py          # 结构化日志（双输出 + request_id）
│   │   ├── tracing.py          # OpenTelemetry 追踪
│   │   ├── rate_limit.py       # 频率限制
│   │   ├── request_context.py  # 请求上下文（request_id 注入）
│   │   └── constants.py        # 全局常量
│   ├── db/                     # 数据访问层
│   │   ├── connection.py       # asyncpg 连接池（pgvector 自动注册）
│   │   └── migrations.py       # 版本化 SQL 迁移
│   ├── memory/                 # 记忆与向量存储
│   │   ├── vector_store.py     # pgvector 封装（长期记忆 + RAG）
│   │   └── rag.py              # 语义切片
│   ├── models/                 # Pydantic 数据模型
│   ├── repositories/           # 数据仓库（SQL 操作）
│   ├── routers/                # API 路由层
│   │   ├── chat.py             # WebSocket 聊天
│   │   ├── auth.py             # 认证
│   │   ├── conversations.py    # 会话管理
│   │   ├── documents.py        # RAG 文档
│   │   ├── manufacturing.py    # 工业智造
│   │   └── admin.py            # 管理后台
│   └── services/               # 业务逻辑层
├── frontend/                   # React 前端
│   ├── src/
│   │   ├── pages/              # 页面（Chat/Login/Admin/Knowledge/Manufacturing/Stats）
│   │   ├── components/         # 组件
│   │   ├── lib/                # API 客户端 + WebSocket
│   │   ├── store/              # Zustand 状态管理
│   │   └── types.ts            # TypeScript 类型
│   └── package.json
├── tests/                      # 测试（7 个测试文件）
├── scripts/                    # 运维脚本（负载测试/DB检查/文档入库）
├── .github/workflows/ci.yml   # CI/CD
├── Dockerfile                  # 多阶段构建
├── docker-compose.yml          # 服务编排
├── requirements.txt            # Python 依赖
├── ruff.toml                   # Lint 配置
├── mypy.ini                    # 类型检查配置
└── pytest.ini                  # 测试配置
```

## API 概览

详细 API 文档访问 http://localhost:8000/docs（Swagger UI）

### 认证

- `POST /api/auth/register` - 用户注册
- `POST /api/auth/login` - 用户登录（返回 access + refresh token）
- `POST /api/auth/refresh` - 刷新 Token
- `GET /api/auth/me` - 当前用户信息

### 聊天（WebSocket）

- `WS /ws/chat?token=xxx` - WebSocket 双向聊天（推荐）
- `POST /api/chat` - 非流式聊天（备用）

### 会话管理

- `GET /api/conversations` - 历史会话列表
- `GET /api/conversations/{id}/messages` - 会话消息
- `DELETE /api/conversations/{id}` - 删除会话

### RAG 文档

- `POST /api/documents/upload` - 上传文档到知识库
- `GET /api/documents` - 文档列表
- `DELETE /api/documents/{filename}` - 删除文档

### 工业智造

- `WS /ws/manufacturing?token=xxx` - 工业 WebSocket 聊天
- `POST /api/manufacturing/knowledge/upload` - 工业知识入库

### 系统

- `GET /api/health` - 健康检查（聚合 PG/pgvector/Ollama/LLM 状态）
- `GET /metrics` - Prometheus 指标

## 测试

```bash
# 需要 PostgreSQL 测试实例
docker compose -f docker-compose.test.yml up -d

# 运行全部测试
pytest tests/ -q

# 运行单个测试文件
pytest tests/test_auth.py -v
```

测试覆盖：认证流程、聊天流、文档上传、图编排、LLM 容错、WebSocket。

## 配置说明

### LLM 容错配置

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| LLM_MAX_RETRIES | 3 | 瞬时错误最大重试次数 |
| LLM_CIRCUIT_FAILURE_THRESHOLD | 5 | 连续失败多少次后熔断 |
| LLM_CIRCUIT_RECOVERY_TIMEOUT | 60 | 熔断冷却秒数 |
| LLM_TOKEN_BUDGET_PER_MINUTE | 0 | 每分钟 token 预算（0=不限） |
| FALLBACK_MODEL_NAME | 空 | 降级模型名（空=不启用） |

### 上传限制

- **图片**：png, jpg, jpeg, gif, bmp, webp
- **文档**：txt, md, csv, json, pdf, docx, html, py, java, js, ts
- **最大文件大小**：20MB

## 常见问题

### Q: 启动报 ModuleNotFoundError？

A: 项目依赖安装在 `libs/` 目录，需设置 `PYTHONPATH=libs` 或使用虚拟环境。

### Q: JWT_SECRET_KEY 校验失败？

A: 密钥必须 ≥32 字符且不含弱占位符。生成强密钥：
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

### Q: pgvector 不可用？

A: 确保 PostgreSQL 已安装 vector 扩展：
```sql
CREATE EXTENSION IF NOT EXISTS vector;
```
Docker Compose 使用的 `pgvector:pg17` 镜像已内置。

### Q: RAG 检索不到内容？

A: 确保 Ollama 已启动且 `nomic-embed-text` 模型已拉取。嵌入失败时文档不会入库。

### Q: 如何更换 LLM？

A: 修改 `.env` 中的 `MODEL_NAME` 和 `OPENAI_BASE_URL`，支持任何 OpenAI 兼容接口。

## 许可证

MIT License

## 联系方式

- GitHub: https://github.com/LKF123456-sys/pythonagent
- 问题反馈: 请在 GitHub Issues 中提交

---

**注意**：本项目仅供学习和研究使用，请遵守相关 API 服务的使用条款。
