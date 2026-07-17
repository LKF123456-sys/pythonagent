# 多智能体对话系统 - 后端 Dockerfile
# 基于 Python 3.11 slim，多阶段构建

# ============================================================
# 阶段1：构建前端（如果有 Node.js 前端项目）
# ============================================================
FROM node:20-alpine AS frontend-builder

WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci --production=false
COPY frontend/ ./
RUN npm run build

# ============================================================
# 阶段2：Python 后端
# ============================================================
FROM python:3.11-slim AS backend

WORKDIR /app

# 系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制后端代码
COPY config.py logger.py database.py auth.py agents.py graph.py memory.py web_app.py main.py ./
COPY .env .env

# 复制前端构建产物（可选，如果不需要 Nginx 托管）
# COPY --from=frontend-builder /app/frontend/dist ./static

# 创建数据目录
RUN mkdir -p data logs uploads

# 暴露端口
EXPOSE 8000

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8000/api/health').raise_for_status()"

# 启动命令
CMD ["uvicorn", "web_app:app", "--host", "0.0.0.0", "--port", "8000"]
