# ---- 阶段1：构建前端 ----
FROM node:20-alpine AS web
WORKDIR /web
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build        # 产物在 /web/dist

# ---- 阶段2：后端运行（同时托管前端 dist）----
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONUTF8=1 PYTHONIOENCODING=utf-8 PIP_NO_CACHE_DIR=1
WORKDIR /app/backend
# 沙箱 docker 后端需要容器内能调宿主 docker（挂 /var/run/docker.sock 起一次性隔离容器跑学生代码）。
# 只装 CLI 客户端（daemon 用宿主的）。注意：Debian 13/trixie 把 docker.io 拆成了
# docker.io(仅 daemon) + docker-cli(客户端命令)——必须装 docker-cli 才有 `docker` 命令，
# 装 docker.io 只会得到 dockerd 而没有客户端。宿主未挂 socket 时 sandbox 自动降级 subprocess。
RUN apt-get update && apt-get install -y --no-install-recommends docker-cli \
    && rm -rf /var/lib/apt/lists/*
COPY backend/requirements.txt ./
RUN pip install -r requirements.txt
COPY backend/ /app/backend/
COPY --from=web /web/dist /app/frontend/dist
EXPOSE 8000
# Render 通过 $PORT 指定端口；本地默认 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
