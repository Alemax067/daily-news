# daily-news backend

News-extraction agent backend. Given a list-page URL and a section name,
the agent learns the page's CSS selectors with an LLM, caches them, and
extracts structured news items (and their detail pages) on subsequent
runs without re-asking the LLM.

Built on FastAPI + SQLite + APScheduler + deepagents (LangGraph).

## What it does

- **Subscriptions**: persist a (URL, section) plus the learned selectors,
  so each refresh just runs BeautifulSoup, no LLM cost.
- **Automation**: scheduler periodically refreshes every enabled
  subscription and inserts new items into `news_items`.
- **Sessions**: the agent runs as a streaming chat session. Clients
  consume Server-Sent Events; disconnect-and-resume is supported.
- **One-shot extraction**: skip the agent and call the extractor
  directly from the CLI for quick scraping.

## Project layout

```
src/
  api.py         FastAPI routes (sessions, subscriptions, automation, news)
  agent.py       deepagents agent + tool registration
  scheduler.py   background worker + cron-ish scheduler
  db.py          SQLAlchemy 2.0 async models + alembic bootstrap
  models.py      Pydantic schemas (in/out)
  extractor.py   fetch + cache + learn + parse pipeline
  fetcher.py     httpx HTML fetcher with encoding detection
  skeleton.py    HTML → de-noised skeleton (avoids LLM content filters)
  learner.py     LLM call that produces CSS selectors
  cache.py       data/selectors.json persistence
  config.py      .env loader (DAILY_NEWS_AGENT_*)
  cli.py         interactive REPL
  main.py        entry dispatcher (serve / chat / extract)
alembic/         schema migrations
```

## Setup

Requires Python 3.13+ and [uv](https://docs.astral.sh/uv/).

```bash
cd backend
uv sync
```

Configure `.env` at the **repo root** (one level up from `backend/`):

```
DAILY_NEWS_AGENT_API_KEY=<your-key>
DAILY_NEWS_AGENT_BASE_URL=https://yunwu.ai/v1
DAILY_NEWS_AGENT_MODEL=deepseek-v4-pro
```

See `.env.example` for all knobs.

## Running

All commands assume `cd backend` first.

### HTTP server (most common)

```bash
uv run alembic -c alembic.ini upgrade head      # apply migrations
uv run python -m src.main serve --port 8765
```

Then hit:

- `POST /sessions` + `POST /sessions/{id}/messages` — chat with the agent
- `GET  /subscriptions` — list saved subscriptions
- `POST /automation/trigger` — manually run a refresh batch
- `GET  /automation/timeline` — per-batch summary
- `POST /extract` — one-shot extraction (legacy, no agent)

Full route list lives at the top of `src/api.py`. OpenAPI docs at
`http://localhost:8765/docs`.

### Interactive REPL

```bash
uv run python -m src.main chat
```

Type a URL and a section name; type `:reset` to clear the session,
`:quit` to exit. Useful for quick agent debugging without spinning up
the frontend.

### One-shot CLI extraction

Skips the agent entirely and runs the extractor pipeline directly.
Fastest way to verify a site is scrapable.

```bash
# list + detail
uv run python -m src.main extract \
  --url https://www.shanghai.gov.cn/nw4411/index.html \
  --section "上海要闻" --max 5

# list only
uv run python -m src.main extract --url ... --section ... --no-detail
```

Output is JSON to stdout.

## Cache

- **File**: `../data/selectors.json` (also mirrored into the SQLite DB
  per subscription).
- **Keys**:
  - `list::{host}{path}::{section}` — list-page selectors
  - `detail::{host}` — detail-page selectors (one template per host)
- **Invalidate**: delete the file, or call the agent tool
  `clear_selector_cache(prefix=...)`.

## Database

SQLite at `../data/app.db`. Schema is managed by Alembic — never edit
the file by hand. To add a migration:

```bash
uv run alembic -c alembic.ini revision --autogenerate -m "describe change"
uv run alembic -c alembic.ini upgrade head
```

`init_db()` auto-runs `upgrade head` on server startup, so deploying a
new revision is just a redeploy.

## Production deployment

Don't run this manually in production — use the Docker setup at the
repo root (`docker compose up -d --build`). The container handles
migrations and starts uvicorn with the frontend mounted on `/`.
