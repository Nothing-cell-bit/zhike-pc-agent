FROM node:22-bookworm-slim AS frontend
WORKDIR /src
COPY frontend/package*.json ./frontend/
RUN cd frontend && npm ci --ignore-scripts
COPY frontend/ ./frontend/
RUN cd frontend && npm run build

FROM python:3.11-slim-bookworm
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends fonts-noto-cjk && rm -rf /var/lib/apt/lists/*
COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ ./backend/
COPY --from=frontend /src/frontend/dist ./frontend/dist/
ENV PYTHONUNBUFFERED=1 STORE_DATA_DIR=/mnt/workspace/zhike COOKIE_SECURE=true MARKETING_KNOWLEDGE_SOURCE=ima
EXPOSE 7860
CMD ["python", "-m", "backend.cloud"]
