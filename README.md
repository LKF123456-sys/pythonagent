# 多智能体对话系统

基于 FastAPI、LangGraph、PostgreSQL/pgvector、Redis、React 和 Docker Compose 构建的准生产级多智能体 AI 对话系统。系统支持联网搜索、图片识别、混合 RAG 检索、长期记忆、Human-in-the-loop 人工审批、WebSocket 流式响应、JWT 双 Token 认证、工业智造垂直领域、多实例部署、Prometheus 指标、Grafana 面板和告警规则。

## 功能特性

### 核心能力

- **多智能体工作流**：基于 LangGraph 构建 `preprocess → supervisor → search/rag/direct → human_review → answer → store_memory` 的可观测工作流。
- **智能路由**：Supervisor 自动判断用户问题是否需要联网搜索、RAG 检索或直接回答。
- **联网搜索**：通过 Tavily API 检索实时互联网信息，并将搜索结果注入回答上下文。
- **图片识别**：通过本地 Ollama 多模态模型识别上传图片内容。
- **混合 RAG 检索**：支持 pgvector 向量检索、PostgreSQL tsvector 关键词检索和加权 reranking 融合。
- **长期记忆**：自动保存对话记忆，按 `user_id` 隔离检索，避免用户间记忆串扰。
- **WebSocket 流式响应**：实时推送节点状态、思考过程、工具调用、回答 token 和完成事件。
- **多轮工具调用**：支持多轮 Function Calling，并通过最大轮数限制防止无限循环。
- **Human-in-the-loop**：敏感操作可触发 LangGraph interrupt，等待人工批准或拒绝后继续执行。
- **工业智造垂直域**：提供故障诊断、工艺优化、预测性维护、工业知识问答和工业文档管理。
- **JWT 双 Token 认证**：支持 Access Token、Refresh Token、登出黑名单和当前用户信息接口。
- **Redis 分布式缓存**：多实例下共享历史上下文缓存，Redis 不可用时自动降级到内存缓存。
- **LLM 容错**：内置超时控制、指数退避重试、熔断器、降级模型和 Token 预算保护。
- **API 版本管理**：全部 HTTP 和 WebSocket 路由统一挂载到 `/api/v1`。
- **监控告警**：Prometheus 指标、Grafana 面板、深度健康检查和告警规则。
- **分布式部署**：Docker Compose 编排 PostgreSQL、Redis、后端多实例、Nginx、Prometheus 和 Grafana。

## 工作流架构

### 通用智能体工作流

```text
START
  ↓
preprocess
  ↓
supervisor
  ├── SEARCH → search ──┐
  ├── RAG    → rag    ──┤
  └── DIRECT ───────────┘
              ↓
        human_review
              ↓
           answer
              ↓
        store_memory
              ↓
             END
```

### 节点说明

| 节点 | 职责 |
|------|------|
| `preprocess` | 图片识别、历史上下文处理、长期记忆和 RAG 预检索 |
| `supervisor` | 判断问题路由：SEARCH、RAG 或 DIRECT |
| `search` | 调用 Tavily 搜索实时信息 |
| `rag` | 从用户上传文档中检索相关上下文 |
| `human_review` | 根据敏感关键词触发人工审批，可暂停并恢复图执行 |
| `answer` | 调用 LLM 生成最终回答，支持流式 token 输出和多轮工具调用 |
| `store_memory` | 将对话写入长期记忆向量库 |

### 工业智造工作流

```text
mfg_preprocess → mfg_supervisor → fault/process/predict/knowledge → mfg_answer → mfg_store
```

通用管线和工业管线共享认证、数据库、WebSocket、缓存、日志、追踪和监控基础设施，但业务逻辑相互隔离。

## 技术栈

### 后端

| 类型 | 技术 |
|------|------|
| Web 框架 | FastAPI / Starlette / Uvicorn / Gunicorn |
| 智能体编排 | LangGraph / LangChain |
| LLM 接口 | DeepSeek API（OpenAI 兼容接口） |
| 本地模型 | Ollama（视觉识别与 embedding） |
| 数据库 | PostgreSQL + asyncpg 连接池 |
| 向量数据库 | pgvector |
| 关键词检索 | PostgreSQL tsvector + GIN 索引 |
| 缓存 | Redis + 内存降级缓存 |
| 联网搜索 | Tavily API |
| 认证 | JWT / python-jose / bcrypt |
| 限流 | slowapi |
| 可观测性 | Prometheus / OpenTelemetry / 结构化日志 |
| 容错 | tenacity 重试 / 熔断器 / 超时 / 降级 / Token 预算 |

### 前端

| 类型 | 技术 |
|------|------|
| UI 框架 | React 18 |
| 类型系统 | TypeScript |
| 构建工具 | Vite |
| 状态管理 | Zustand |
| 路由 | React Router |
| 动画 | Framer Motion |
| Markdown | react-markdown + remark-gfm |
| 通信 | Axios + WebSocket |

### 部署与运维

| 类型 | 技术 |
|------|------|
| 容器化 | Docker 多阶段构建 |
| 编排 | Docker Compose |
| 后端多进程 | Gunicorn + UvicornWorker |
| 负载均衡 | Nginx HTTP/WebSocket 代理 |
| 缓存服务 | Redis 7 Alpine |
| 数据库服务 | pgvector/pgvector:pg17 |
| 监控 | Prometheus |
| 可视化 | Grafana |
| CI/CD | GitHub Actions |
| 代码质量 | ruff / mypy / pytest / TypeScript build |

## 快速开始

### 环境要求

- Python 3.11+
- Node.js 20+
- Docker Desktop 或 Docker Engine
- PostgreSQL 17 + pgvector（Docker Compose 可自动提供）
- Redis（Docker Compose 可自动提供）
- Ollama
- DeepSeek API Key
- Tavily API Key

### 1. 克隆项目

```bash
git clone https://github.com/LKF123456-sys/pythonagent.git
cd pythonagent/multi_agent_system
```

### 2. 安装依赖

```bash
pip install -r requirements.txt --target libs
cd frontend
npm install
cd ..
```

### 3. 配置环境变量

```bash
cp .env.example .env
```

关键配置项：

| 配置项 | 说明 |
|--------|------|
| `OPENAI_API_KEY` | DeepSeek API 密钥 |
| `OPENAI_BASE_URL` | OpenAI 兼容接口地址，默认 DeepSeek |
| `MODEL_NAME` | 主力对话模型 |
| `TAVILY_API_KEY` | Tavily 联网搜索密钥 |
| `DATABASE_URL` | PostgreSQL 连接串 |
| `REDIS_ENABLED` | 是否启用 Redis 缓存 |
| `REDIS_URL` | Redis 连接地址 |
| `JWT_SECRET_KEY` | JWT 强随机密钥，生产环境必须替换 |
| `API_V1_PREFIX` | API 版本前缀，默认 `/api/v1` |
| `HITL_ENABLED` | 是否启用人工审批 |
| `HYBRID_SEARCH_ENABLED` | 是否启用混合检索 |

### 4. 启动 Ollama 模型

```bash
ollama serve
ollama pull qwen3
ollama pull nomic-embed-text
```

如果使用图片识别，请根据机器性能拉取合适的视觉模型，并在 `.env` 中配置 `OLLAMA_VISION_MODEL`。

### 5. 开发模式启动后端

```powershell
$env:PYTHONPATH="libs"
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

访问地址：

- Web 页面：http://localhost:8000
- Swagger UI：http://localhost:8000/docs
- ReDoc：http://localhost:8000/redoc
- Prometheus 指标：http://localhost:8000/metrics
- 深度健康检查：http://localhost:8000/api/v1/health/deep

### 6. 开发模式启动前端

```bash
cd frontend
npm run dev
```

访问地址：http://localhost:5173

前端开发代理已支持：

- HTTP API：`/api/v1/**`
- WebSocket：`/api/v1/ws/**`
- Prometheus：`/metrics`

## Docker Compose 一键部署

```bash
docker compose up -d --build
```

服务说明：

| 服务 | 默认端口 | 说明 |
|------|----------|------|
| `nginx` | 80 | 统一入口，代理 HTTP 与 WebSocket |
| `backend` | 容器内部 8000 | FastAPI 后端，可多实例扩展 |
| `db` | 5433 -> 5432 | PostgreSQL + pgvector |
| `redis` | 6380 -> 6379 | Redis 分布式缓存 |
| `prometheus` | 9090 | 指标抓取与告警规则 |
| `grafana` | 3001 -> 3000 | 可视化监控面板 |

常用命令：

```bash
# 查看服务状态
docker compose ps

# 查看后端日志
docker compose logs -f backend

# 查看 Nginx 日志
docker compose logs -f nginx

# 停止服务
docker compose down
```

## 项目结构

```text
multi_agent_system/
├── app/
│   ├── main.py                    # FastAPI 应用工厂、生命周期、中间件、路由注册
│   ├── agents/
│   │   ├── graph.py               # LangGraph 通用工作流编排
│   │   ├── nodes.py               # 通用智能体节点实现
│   │   ├── llm.py                 # LLM 创建、标题生成、上下文压缩、超时降级
│   │   ├── resilience.py          # 重试、熔断、降级、Token 预算
│   │   ├── stream_parser.py       # 流式标签解析器
│   │   ├── runtime.py             # 运行时依赖注册
│   │   └── manufacturing/         # 工业智造垂直领域智能体
│   ├── core/
│   │   ├── cache.py               # Redis 分布式缓存与内存降级
│   │   ├── config.py              # pydantic-settings 配置中心
│   │   ├── security.py            # JWT、bcrypt、文件安全
│   │   ├── exceptions.py          # 自定义异常体系
│   │   ├── logging.py             # 结构化日志
│   │   ├── tracing.py             # OpenTelemetry 链路追踪
│   │   ├── rate_limit.py          # 请求限流
│   │   ├── request_context.py     # request_id 上下文
│   │   └── constants.py           # 全局常量
│   ├── db/
│   │   ├── connection.py          # asyncpg 连接池与事务上下文
│   │   └── migrations.py          # 版本化数据库迁移、pgvector、全文索引
│   ├── memory/
│   │   ├── vector_store.py        # 向量检索、关键词检索、reranking 融合
│   │   └── rag.py                 # 文档语义切片与上下文格式化
│   ├── models/                    # Pydantic 请求/响应模型
│   ├── repositories/              # 数据仓库层
│   ├── routers/                   # API/WebSocket 路由层
│   └── services/                  # 业务逻辑层
├── frontend/                      # React + TypeScript 前端
├── monitoring/
│   ├── prometheus/                # Prometheus 配置与告警规则
│   └── grafana/                   # Grafana 数据源与仪表盘
├── nginx/                         # Nginx 反向代理与 WebSocket 代理配置
├── tests/                         # pytest 测试套件
├── scripts/                       # 运维脚本、压测脚本、RAG 验证脚本
├── gunicorn_conf.py               # Gunicorn 多 worker 配置
├── Dockerfile                     # 后端和前端一体化镜像构建
├── docker-compose.yml             # 分布式部署编排
├── requirements.txt               # Python 依赖
├── API.md                         # HTTP/WebSocket API 文档
└── README.md                      # 项目说明
```

## API 概览

所有业务接口统一使用 `/api/v1` 前缀。

### 认证

- `POST /api/v1/auth/register`：用户注册
- `POST /api/v1/auth/login`：用户登录
- `POST /api/v1/auth/refresh`：刷新 Token
- `POST /api/v1/auth/logout`：登出并撤销 Refresh Token
- `GET /api/v1/auth/me`：获取当前用户

### 通用聊天

- `WS /api/v1/ws/chat/{session_id}?token=xxx`：WebSocket 流式聊天
- `POST /api/v1/chat`：非流式聊天
- `POST /api/v1/chat/upload-image`：上传聊天图片

### 会话管理

- `GET /api/v1/conversations`：会话列表
- `GET /api/v1/conversations/{session_id}/messages`：会话消息
- `PATCH /api/v1/conversations/{session_id}`：重命名会话
- `DELETE /api/v1/conversations/{session_id}`：删除会话
- `GET /api/v1/conversations/{session_id}/export`：导出会话
- `GET /api/v1/stats/tokens`：Token 用量统计

### RAG 文档

- `POST /api/v1/documents/upload`：上传文档并入库
- `GET /api/v1/documents`：文档列表
- `DELETE /api/v1/documents/{filename}`：删除文档

### 工业智造

- `WS /api/v1/ws/manufacturing/{session_id}?token=xxx`：工业 WebSocket 聊天
- `GET /api/v1/mfg/fault-codes`：查询故障码
- `GET /api/v1/mfg/equipment`：查询设备信息
- `POST /api/v1/mfg/upload-image`：上传工业图片
- `POST /api/v1/mfg/documents/upload`：上传工业文档
- `GET /api/v1/mfg/documents`：工业文档列表
- `DELETE /api/v1/mfg/documents/{filename}`：删除工业文档
- `GET /api/v1/uploads/{filename}`：访问已上传图片

### 人工审批

- `POST /api/v1/review/approve`：批准被 interrupt 暂停的请求
- `POST /api/v1/review/reject`：拒绝被 interrupt 暂停的请求

### 系统与监控

- `GET /api/v1/health`：基础健康检查
- `GET /api/v1/health/deep`：深度健康检查
- `GET /metrics`：Prometheus 指标

完整接口说明见 [API.md](./API.md)。

## 混合检索说明

系统支持两路检索后融合排序：

1. **向量检索**：使用 pgvector cosine distance 检索语义相似内容。
2. **关键词检索**：使用 PostgreSQL tsvector + GIN 索引检索关键词匹配内容。
3. **加权融合**：默认关键词权重 `0.3`，向量权重 `0.7`，最终取融合分数最高的结果。

相关配置：

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `HYBRID_SEARCH_ENABLED` | `True` | 是否启用混合检索 |
| `HYBRID_KEYWORD_WEIGHT` | `0.3` | 关键词检索权重 |
| `HYBRID_RERANK_TOP_K` | `20` | reranking 前候选数量 |
| `RERANK_MODEL` | 空 | 预留 reranking 模型配置 |

## Human-in-the-loop 说明

默认关闭人工审批。启用方式：

```env
HITL_ENABLED=true
HITL_SENSITIVE_KEYWORDS=删除,移除,清空,重置,执行,下载,安装
```

当用户问题包含敏感关键词时，工作流会在 `human_review` 节点暂停，等待人工通过 `/api/v1/review/approve` 或 `/api/v1/review/reject` 恢复执行。

## 监控与告警

### Prometheus

配置文件位于：

- `monitoring/prometheus/prometheus.yml`
- `monitoring/prometheus/alert_rules.yml`

内置告警：

| 告警 | 触发条件 |
|------|----------|
| `CircuitBreakerOpen` | LLM 熔断器打开 |
| `HighTokenUsage` | Token 消耗速率过高 |
| `LLMSlowResponse` | LLM P95 响应时间超过阈值 |
| `ServiceDown` | 后端服务不可用 |
| `HighErrorRate` | 5xx 错误率过高 |

### Grafana

访问地址：http://localhost:3001

默认账号：

```text
admin / admin
```

仪表盘文件位于：

```text
monitoring/grafana/dashboards/agent_dashboard.json
```

## 测试

```bash
# 运行全部测试
pytest tests/ -q

# 查看覆盖率
pytest tests/ --cov=app --cov-report=term-missing

# 前端构建验证
cd frontend
npm run build
```

当前测试套件覆盖配置、安全、异常、模型、RAG、流式解析、缓存和容错模块，测试覆盖率目标为 70% 以上。

## 常见问题

### Q: 前端一直显示“重连中”？

A: 请确认前端 WebSocket 连接的是版本化路径：

```text
/api/v1/ws/chat/{session_id}
```

开发环境需要确认 `frontend/vite.config.ts` 已代理 `/api/v1/ws`，生产环境需要确认 Nginx 已代理 `/api/v1/ws/` 并保留 WebSocket Upgrade 头。

### Q: 启动报 `ModuleNotFoundError`？

A: 如果依赖安装到 `libs/` 目录，需要设置 `PYTHONPATH=libs`。也可以改用虚拟环境安装依赖。

### Q: `JWT_SECRET_KEY` 校验失败？

A: 生产环境必须使用不少于 32 字符的强随机密钥。生成方式：

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

### Q: RAG 检索不到内容？

A: 请检查 Ollama 是否启动、embedding 模型是否拉取、数据库迁移是否执行、文档是否成功切片入库。

### Q: Redis 连接失败会导致系统不可用吗？

A: 不会。`CacheService` 会自动降级到内存缓存，但多实例下缓存不再共享。

## 许可证

MIT License

## 联系方式

- GitHub: https://github.com/LKF123456-sys/pythonagent
- 问题反馈: 请在 GitHub Issues 中提交

---

**注意**：本项目仅供学习和研究使用，请遵守相关 API 服务和模型服务的使用条款。
