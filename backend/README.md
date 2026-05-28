# daily-news backend

新闻抓取智能体:输入 URL + 板块名,自动学习页面结构,返回结构化新闻列表与详情。

## 架构

```
用户输入(url, section)
        │
        ▼
deepagents 智能体  ←── HTTP /chat 或 CLI REPL
        │
        └─ tool: extract_news / extract_list_only / extract_detail / clear_selector_cache
                │
                ├─ 1. cache 命中 → 用 CSS 选择器解析(BeautifulSoup)
                └─ 2. cache 未中 → DOM 骨架(脱敏)→ LLM 学习选择器 → 写入缓存
```

## 模块

| 文件 | 作用 |
|---|---|
| `src/config.py` | 读 `.env` (DAILY_NEWS_AGENT_*) |
| `src/models.py` | Pydantic schemas: NewsItem / NewsDetail / Selectors |
| `src/fetcher.py` | httpx 抓 HTML(带编码探测) |
| `src/cache.py` | `data/selectors.json` 持久化 |
| `src/skeleton.py` | HTML → 脱敏骨架(避开内容过滤) |
| `src/learner.py` | 调 LLM 推断 CSS 选择器 |
| `src/extractor.py` | 高层流程:fetch + cache + learn + parse |
| `src/agent.py` | deepagents 智能体 + 工具注册 |
| `src/api.py` | FastAPI: `/extract`, `/detail`, `/chat` |
| `src/cli.py` | 交互式 REPL |
| `src/main.py` | 入口分发(serve/chat/extract) |

## 运行

```bash
cd backend

# 一次性提取(不走智能体,最快)
uv run python -m src.main extract \
  --url https://www.shanghai.gov.cn/nw4411/index.html \
  --section 上海要闻 --max 5

# 不要详情
uv run python -m src.main extract --url ... --section ... --no-detail

# 启动 HTTP API
uv run python -m src.main serve --port 8000
# POST http://localhost:8000/extract  body: {"url":"...","section":"...","with_detail":true}
# POST http://localhost:8000/chat     body: {"message":"...","session_id":"..."}

# 进入对话式 REPL
uv run python -m src.main chat
```

## 缓存

- 文件:`../data/selectors.json`
- key 格式:
  - `list::{host}{path}::{section}` — 列表页选择器
  - `detail::{host}` — 详情页选择器(同站点共用模板)
- 通过 agent 工具 `clear_selector_cache(prefix=...)` 或直接删文件清除

## 已知问题

- `yunwu.ai` 网关偶发 429 限流;再试或换模型即可
- 政府站点详情页结构差异较大,LLM 偶尔会把 title/date/source 选择器搞错,但 `content` 一般正确
