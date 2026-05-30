# syntax=docker/dockerfile:1.7

# ===== Stage 1: build frontend =====
FROM node:20-alpine AS frontend-builder

WORKDIR /build

RUN corepack enable && corepack prepare pnpm@latest --activate

COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

COPY frontend/ ./
RUN pnpm build


# ===== Stage 2: backend runtime =====
FROM python:3.13-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/backend/.venv \
    PATH="/app/backend/.venv/bin:/root/.local/bin:${PATH}" \
    DAILY_NEWS_FRONTEND_DIST=/app/frontend/dist

# uv: fast Python package manager (matches the project's dev workflow)
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && curl -LsSf https://astral.sh/uv/install.sh | sh

WORKDIR /app/backend

COPY backend/pyproject.toml backend/uv.lock ./
COPY backend/main.py ./
COPY backend/src ./src
RUN uv sync --frozen --no-dev

COPY backend/alembic.ini ./
COPY backend/alembic ./alembic

COPY --from=frontend-builder /build/dist /app/frontend/dist

COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

WORKDIR /app
RUN mkdir -p /app/data
VOLUME ["/app/data"]

EXPOSE 8765

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
