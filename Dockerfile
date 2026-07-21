# 多智能体对话系统 - 单容器部署 Dockerfile
# 多阶段构建：前端（Node 构建静态资源）→ 后端（Python + 内嵌前端，单端口提供全部服务）
#
# 安全说明：
#   - 不 COPY .env 进镜像（敏感配置通过运行时 env_file / environment 注入）
#   - 应用启动时会校验 JWT_SECRET_KEY，弱密钥直接拒绝启动

# ============================================================
# 阶段1：构建前端静态资源
# ============================================================
FROM node:20-alpine AS frontend-builder

ARG NODE_ENV=production
ENV NODE_ENV=${NODE_ENV}

WORKDIR /build
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ============================================================
# 阶段2：Python 后端（内嵌前端静态资源）
# ============================================================
FROM python:3.11-slim AS backend

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# 编译依赖（部分 Python 包需要 gcc）
RUN apt-get update && apt-get install -y --no-install-recommends gcc \
    && rm -rf /var/lib/apt/lists/*

# 先安装依赖（独立成层，充分利用 Docker 构建缓存）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制后端代码（新分层架构 app/ 包 + 启动入口）
COPY app/ ./app/
COPY main.py .

# 复制前端构建产物：app/main.py 的 _mount_frontend 会从 frontend/dist 挂载
# 使单容器即可同时提供 API / WebSocket / 前端页面（同源，无需反向代理）
COPY --from=frontend-builder /build/dist ./frontend/dist

# 运行时日志 / 上传目录（建议通过 volume 持久化）
RUN mkdir -p logs uploads

EXPOSE 8000

# 深度健康检查：/api/health 聚合 PostgreSQL/pgvector/Ollama/LLM 状态，
# 仅当整体 status 为 unhealthy（关键组件数据库故障）时判定容器不健康
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD python -c "import httpx,sys; r=httpx.get('http://localhost:8000/api/health',timeout=5); r.raise_for_status(); sys.exit(1 if r.json().get('status')=='unhealthy' else 0)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
