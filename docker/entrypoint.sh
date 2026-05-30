#!/bin/sh
# Container entrypoint:
#   1) fail fast if the LLM API key is missing
#   2) run pending Alembic migrations against the mounted SQLite db
#   3) start uvicorn on dual-stack (::) so IPv4 and IPv6 both work
set -eu

if [ -z "${DAILY_NEWS_AGENT_API_KEY:-}" ]; then
  echo "[entrypoint] ERROR: DAILY_NEWS_AGENT_API_KEY is empty." >&2
  echo "[entrypoint] Pass it via 'docker run --env-file .env ...' or compose 'env_file:'." >&2
  exit 1
fi

mkdir -p /app/data

cd /app/backend
echo "[entrypoint] running alembic upgrade head"
alembic -c alembic.ini upgrade head

echo "[entrypoint] starting uvicorn on 0.0.0.0:8765"
exec uvicorn src.api:app --host 0.0.0.0 --port 8765 --app-dir /app/backend
