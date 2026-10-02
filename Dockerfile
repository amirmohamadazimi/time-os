# One image runs everything: the API serves the built UI. Used by docker compose and by Render.
FROM node:22-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
RUN pip install --no-cache-dir "uv==0.8.17"
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project --extra postgres

COPY backend/alembic.ini ./
COPY backend/migrations ./migrations
COPY backend/app ./app
COPY --from=web /web/dist ./static

RUN useradd --system --uid 10001 --home /app timeos && mkdir -p /app/data && chown timeos /app/data
USER timeos

ENV TIMEOS_STATIC_DIR=/app/static \
    TIMEOS_DATABASE_URL=sqlite:////app/data/timeos.db
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=15s --retries=5 \
  CMD ["sh", "-c", "python -c \"import urllib.request; urllib.request.urlopen('http://127.0.0.1:${PORT:-8000}/api/health', timeout=2)\""]
# Migrations run on startup. PORT is set by hosts such as Render; 8000 otherwise.
CMD ["sh", "-c", "exec uvicorn app.main:create_app --factory --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers"]
