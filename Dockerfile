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
COPY backend/requirements.txt ./
RUN pip install -r requirements.txt
COPY backend/ /app/backend/
COPY --from=web /web/dist /app/frontend/dist
EXPOSE 8000
# Render 通过 $PORT 指定端口；本地默认 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
