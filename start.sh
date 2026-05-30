#!/usr/bin/env bash
# Linux / macOS one-click launcher.
set -euo pipefail

cd "$(dirname "$0")"

if [ ! -f .env ]; then
  if [ -f .env.example ]; then
    cp .env.example .env
    echo "[i] copied .env.example to .env"
    echo "[!] open .env, fill in DAILY_NEWS_AGENT_API_KEY, then re-run ./start.sh"
    exit 1
  fi
  echo "[x] neither .env nor .env.example present"
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "[x] docker is not installed or not in PATH"
  exit 1
fi

echo "[i] building image and starting container ..."
docker compose up -d --build

echo
echo "[OK] daily-news is running. Open http://localhost:8765"
echo "     IPv6:       http://[::1]:8765"
echo "     tail logs:  docker compose logs -f"
echo "     stop:       docker compose down"
