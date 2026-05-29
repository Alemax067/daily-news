"""FastAPI service: subscriptions + agent sessions (SSE) + news.

Routes:
- /sessions  POST/GET/DELETE,  /sessions/{id}/messages (SSE start),
  /sessions/{id}/stream (SSE resume),  /sessions/{id}/confirm
- /subscriptions  GET/DELETE,  /subscriptions/{id}/refresh,  /subscriptions/{id}/news
- /news/{id}  GET
- /extract,  /detail  (legacy direct calls)

Session streaming model
-----------------------
Each agent turn runs as a detached `asyncio.Task` writing into a shared
event buffer (`StreamRun`). Clients subscribe via SSE; client disconnect
does NOT cancel the producer, so a page refresh can re-attach via
`GET /sessions/{id}/stream` and replay the buffer + continue live.

Two gates protect `confirm_session`:
  1. Both list AND detail selectors must have been learned (verified).
  2. No active stream may be in flight.
"""

from __future__ import annotations

import asyncio
import json
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncIterator

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from . import cache as cache_mod
from . import extractor
from .agent import build_agent
from .db import (
    DB_PATH,
    ChatSession,
    NewsItemRow,
    Subscription,
    dispose_db,
    get_session,
    init_db,
)
from .extractor import extract_detail, extract_list_only, extract_news
from .fetcher import clear_fetch_cache
from .models import (
    ChatMessageOut,
    DetailSelectors,
    ExtractRequest,
    ListSelectors,
    NewsItemDetailOut,
    NewsItemOut,
    RefreshOut,
    SessionConfirmOut,
    SessionCreateIn,
    SessionCreateOut,
    SessionMessageIn,
    SessionOut,
    SubscriptionDetailOut,
    SubscriptionOut,
)


# ===== detached agent runs =====


@dataclass
class StreamRun:
    """One agent turn running detached from any HTTP connection.

    Multiple SSE subscribers can independently iterate `events` from their
    own position; new appends fire `cond.notify_all()` to wake them.
    """

    session_id: str
    events: list[dict[str, Any]] = field(default_factory=list)
    done: bool = False
    cond: asyncio.Condition = field(default_factory=asyncio.Condition)
    task: asyncio.Task[None] | None = None


_state: dict[str, Any] = {}
_streams: dict[str, StreamRun] = {}


@asynccontextmanager
async def _lifespan(app: FastAPI):
    await init_db()
    async with AsyncExitStack() as stack:
        checkpointer = await stack.enter_async_context(
            AsyncSqliteSaver.from_conn_string(str(DB_PATH))
        )
        await checkpointer.setup()
        agent = build_agent(checkpointer=checkpointer)
        _state["checkpointer"] = checkpointer
        _state["agent"] = agent
        try:
            yield
        finally:
            # 1. cancel any in-flight stream producers and wait for them to
            #    unwind so they don't write to checkpointer mid-shutdown.
            tasks = [
                run.task
                for run in _streams.values()
                if run.task is not None and not run.task.done()
            ]
            for t in tasks:
                t.cancel()
            if tasks:
                await asyncio.wait(tasks, timeout=2.0)
            _streams.clear()
            _state.clear()
            clear_fetch_cache()
            # 2. release SQLAlchemy's pooled connections so SQLite can
            #    checkpoint WAL → main DB. Without this, .db-wal and .db-shm
            #    linger after process exit.
            await dispose_db()
        # 3. AsyncExitStack exits here → AsyncSqliteSaver closes its own
        #    sqlite connection. Order matters: dispose_db before this so
        #    no SQLAlchemy connection holds the WAL open.


app = FastAPI(title="daily-news agent", lifespan=_lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:4321", "http://127.0.0.1:4321"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ===== helpers =====


def _agent():
    a = _state.get("agent")
    if a is None:
        raise HTTPException(status_code=503, detail="agent not initialized")
    return a


def _msg_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for b in content:
            if isinstance(b, str):
                parts.append(b)
            elif isinstance(b, dict):
                if b.get("type") == "text":
                    parts.append(b.get("text", ""))
                elif "text" in b:
                    parts.append(str(b["text"]))
        return "".join(parts)
    return str(content)


def _to_chat_messages(msgs: list[BaseMessage]) -> list[ChatMessageOut]:
    out: list[ChatMessageOut] = []
    for m in msgs:
        if isinstance(m, SystemMessage):
            continue
        if isinstance(m, HumanMessage):
            out.append(ChatMessageOut(role="user", content=_msg_text(m.content)))
        elif isinstance(m, AIMessage):
            tcs = getattr(m, "tool_calls", None) or None
            out.append(
                ChatMessageOut(
                    role="assistant",
                    content=_msg_text(m.content),
                    tool_calls=[
                        {"name": t.get("name"), "args": t.get("args")}
                        for t in (tcs or [])
                    ]
                    or None,
                )
            )
        elif isinstance(m, ToolMessage):
            out.append(
                ChatMessageOut(
                    role="tool",
                    content=_msg_text(m.content),
                    tool_name=getattr(m, "name", None),
                )
            )
    return out


def _sub_to_out(s: Subscription, item_count: int = 0) -> SubscriptionOut:
    return SubscriptionOut(
        id=s.id,
        alias=s.alias,
        url=s.url,
        section=s.section,
        last_refreshed_at=s.last_refreshed_at,
        item_count=item_count,
        created_at=s.created_at,
    )


def _is_streaming(session_id: str) -> bool:
    run = _streams.get(session_id)
    return run is not None and not run.done


def _sse(event: str, data: Any) -> str:
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


async def _push_event(run: StreamRun, ev: dict[str, Any]) -> None:
    async with run.cond:
        run.events.append(ev)
        run.cond.notify_all()


async def _mark_done(run: StreamRun) -> None:
    async with run.cond:
        if not run.done:
            run.events.append({"event": "done", "data": {}})
            run.done = True
            run.cond.notify_all()


async def _run_agent_turn(
    run: StreamRun, agent: Any, config: dict[str, Any], content: str
) -> None:
    """Producer: drives the agent and appends translated events to the buffer.

    Survives client disconnect — only stops on completion, error, or
    explicit task.cancel() (server shutdown / new turn supersedes).
    """
    await _push_event(run, {"event": "start", "data": {"user_message": content}})
    try:
        with cache_mod.session_store(run.session_id, str(DB_PATH)):
            async for event in agent.astream_events(
                {"messages": [HumanMessage(content=content)]},
                config=config,
                version="v2",
            ):
                kind = event.get("event")
                if kind == "on_chat_model_stream":
                    chunk = event.get("data", {}).get("chunk")
                    text = (
                        _msg_text(getattr(chunk, "content", ""))
                        if chunk is not None
                        else ""
                    )
                    if text:
                        await _push_event(run, {"event": "token", "data": {"text": text}})
                elif kind == "on_tool_start":
                    name = event.get("name") or event.get("data", {}).get("name")
                    inp = event.get("data", {}).get("input")
                    await _push_event(
                        run,
                        {"event": "tool_start", "data": {"name": name, "input": inp}},
                    )
                elif kind == "on_tool_end":
                    name = event.get("name") or event.get("data", {}).get("name")
                    await _push_event(run, {"event": "tool_end", "data": {"name": name}})
    except asyncio.CancelledError:
        await _push_event(run, {"event": "error", "data": {"error": "cancelled"}})
        raise
    except Exception as e:
        await _push_event(run, {"event": "error", "data": {"error": str(e)}})
    finally:
        await _mark_done(run)


async def _iter_run(run: StreamRun) -> AsyncIterator[str]:
    """Subscriber: yields SSE frames from `events`, blocking on cond when caught up."""
    pos = 0
    while True:
        async with run.cond:
            while pos >= len(run.events) and not run.done:
                await run.cond.wait()
            available = run.events[pos:]
            done = run.done
        for ev in available:
            yield _sse(ev["event"], ev["data"])
            pos += 1
        if done and pos >= len(run.events):
            return


# ===== sessions =====


@app.post("/sessions", response_model=SessionCreateOut)
async def create_session(
    body: SessionCreateIn, db: AsyncSession = Depends(get_session)
) -> SessionCreateOut:
    alias = body.alias.strip()
    if not alias:
        raise HTTPException(status_code=400, detail="订阅别名不能为空")
    existing = (
        await db.execute(select(Subscription).where(Subscription.alias == alias))
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail=f"订阅别名「{alias}」已存在")
    sess = ChatSession(alias=alias, url=body.url, section=body.section, status="draft")
    db.add(sess)
    await db.commit()
    return SessionCreateOut(session_id=sess.id, status="draft")


@app.get("/sessions/{session_id}", response_model=SessionOut)
async def get_session_endpoint(
    session_id: str, db: AsyncSession = Depends(get_session)
) -> SessionOut:
    sess = await db.get(ChatSession, session_id)
    if sess is None:
        raise HTTPException(status_code=404, detail="session not found")

    agent = _agent()
    config = {"configurable": {"thread_id": session_id}}
    state = await agent.aget_state(config)
    messages: list[BaseMessage] = []
    if state is not None and state.values:
        messages = state.values.get("messages", []) or []
    return SessionOut(
        id=sess.id,
        status=sess.status,  # type: ignore[arg-type]
        alias=sess.alias,
        url=sess.url,
        section=sess.section,
        subscription_id=sess.subscription_id,
        is_streaming=_is_streaming(session_id),
        messages=_to_chat_messages(messages),
    )


@app.delete("/sessions/{session_id}")
async def delete_session_endpoint(
    session_id: str, db: AsyncSession = Depends(get_session)
) -> dict[str, bool]:
    sess = await db.get(ChatSession, session_id)
    if sess is None:
        raise HTTPException(status_code=404, detail="session not found")
    run = _streams.get(session_id)
    if run is not None and run.task is not None and not run.task.done():
        run.task.cancel()
    _streams.pop(session_id, None)
    if sess.status == "draft":
        sess.status = "abandoned"
        await db.commit()
    return {"ok": True}


@app.post("/sessions/{session_id}/messages")
async def post_session_message(
    session_id: str,
    body: SessionMessageIn,
    db: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    sess = await db.get(ChatSession, session_id)
    if sess is None:
        raise HTTPException(status_code=404, detail="session not found")
    if sess.status != "draft":
        raise HTTPException(status_code=409, detail=f"session is {sess.status}")

    if _is_streaming(session_id):
        raise HTTPException(
            status_code=409, detail="智能体正在回复中,请等当前轮结束再发送"
        )

    # Replace any prior completed run for this session.
    _streams.pop(session_id, None)

    agent = _agent()
    config = {"configurable": {"thread_id": session_id}, "recursion_limit": 100}
    run = StreamRun(session_id=session_id)
    _streams[session_id] = run
    run.task = asyncio.create_task(_run_agent_turn(run, agent, config, body.content))

    return StreamingResponse(
        _iter_run(run),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/sessions/{session_id}/stream")
async def stream_session(session_id: str) -> StreamingResponse:
    """Resume subscription to an in-flight (or just-completed) agent run.

    The buffer is replayed from index 0 so a fresh client rebuilds full
    state without needing prior event ids; live tail is then streamed.
    """
    run = _streams.get(session_id)
    if run is None:
        raise HTTPException(status_code=404, detail="无活动或已缓存的流")
    return StreamingResponse(
        _iter_run(run),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/sessions/{session_id}/confirm", response_model=SessionConfirmOut)
async def confirm_session(
    session_id: str, db: AsyncSession = Depends(get_session)
) -> SessionConfirmOut:
    sess = await db.get(ChatSession, session_id)
    if sess is None:
        raise HTTPException(status_code=404, detail="session not found")
    if sess.status == "confirmed" and sess.subscription_id:
        return SessionConfirmOut(subscription_id=sess.subscription_id)
    if sess.status != "draft":
        raise HTTPException(status_code=409, detail=f"session is {sess.status}")

    # 闸 2: never confirm while the agent is still talking.
    if _is_streaming(session_id):
        raise HTTPException(
            status_code=409, detail="智能体正在回复中,请等回复完成再保存"
        )

    # 闸 1a: list selectors required.
    list_sel: ListSelectors | None = None
    if sess.list_selectors_json:
        cache_dict = json.loads(sess.list_selectors_json)
        raw = cache_dict.get(cache_mod.list_key(sess.url, sess.section))
        if raw:
            list_sel = ListSelectors.model_validate(raw)
    if list_sel is None:
        raise HTTPException(
            status_code=400,
            detail="智能体还没成功抓过列表,请继续对话直到看到新闻表格再保存",
        )
    # 闸 1b: detail selectors required — verifies the full pipeline ran end-to-end.
    detail_sel: DetailSelectors | None = None
    if sess.detail_selectors_json:
        cache_dict = json.loads(sess.detail_selectors_json)
        raw = cache_dict.get(cache_mod.detail_key(sess.url))
        if raw:
            detail_sel = DetailSelectors.model_validate(raw)
    if detail_sel is None:
        raise HTTPException(
            status_code=400,
            detail="智能体还没成功抓过详情,请等智能体把至少一条新闻的正文抓出来再保存",
        )

    sub = Subscription(
        alias=sess.alias,
        url=sess.url,
        section=sess.section,
        list_selectors_json=list_sel.model_dump_json(),
        detail_selectors_json=detail_sel.model_dump_json(),
    )
    db.add(sub)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=409, detail=f"订阅别名「{sess.alias}」已存在"
        ) from None

    sess.status = "confirmed"
    sess.subscription_id = sub.id
    await db.commit()
    _streams.pop(session_id, None)
    return SessionConfirmOut(subscription_id=sub.id)


# ===== subscriptions =====


@app.get("/subscriptions", response_model=list[SubscriptionOut])
async def list_subscriptions(
    db: AsyncSession = Depends(get_session),
) -> list[SubscriptionOut]:
    rows = (
        (
            await db.execute(
                select(
                    Subscription,
                    func.count(NewsItemRow.id).label("cnt"),
                )
                .outerjoin(NewsItemRow, NewsItemRow.subscription_id == Subscription.id)
                .group_by(Subscription.id)
                .order_by(Subscription.created_at.desc())
            )
        )
        .all()
    )
    return [_sub_to_out(s, cnt) for s, cnt in rows]


@app.get("/subscriptions/{sub_id}", response_model=SubscriptionDetailOut)
async def get_subscription(
    sub_id: str, db: AsyncSession = Depends(get_session)
) -> SubscriptionDetailOut:
    sub = await db.get(Subscription, sub_id)
    if sub is None:
        raise HTTPException(status_code=404, detail="subscription not found")
    cnt = (
        await db.execute(
            select(func.count(NewsItemRow.id)).where(
                NewsItemRow.subscription_id == sub.id
            )
        )
    ).scalar_one()
    return SubscriptionDetailOut(
        id=sub.id,
        alias=sub.alias,
        url=sub.url,
        section=sub.section,
        created_at=sub.created_at,
        last_refreshed_at=sub.last_refreshed_at,
        item_count=cnt,
        list_selectors=ListSelectors.model_validate_json(sub.list_selectors_json),
        detail_selectors=(
            DetailSelectors.model_validate_json(sub.detail_selectors_json)
            if sub.detail_selectors_json
            else None
        ),
    )


@app.delete("/subscriptions/{sub_id}")
async def delete_subscription(
    sub_id: str, db: AsyncSession = Depends(get_session)
) -> dict[str, bool]:
    sub = await db.get(Subscription, sub_id)
    if sub is None:
        raise HTTPException(status_code=404, detail="subscription not found")
    await db.delete(sub)
    await db.commit()
    return {"ok": True}


@app.post("/subscriptions/{sub_id}/refresh", response_model=RefreshOut)
async def refresh_subscription(
    sub_id: str, db: AsyncSession = Depends(get_session)
) -> RefreshOut:
    sub = await db.get(Subscription, sub_id)
    if sub is None:
        raise HTTPException(status_code=404, detail="subscription not found")

    list_sel = ListSelectors.model_validate_json(sub.list_selectors_json)
    detail_sel = (
        DetailSelectors.model_validate_json(sub.detail_selectors_json)
        if sub.detail_selectors_json
        else None
    )

    try:
        records = await asyncio.to_thread(
            extractor.extract_with_rule,
            url=sub.url,
            list_selectors=list_sel,
            detail_selectors=detail_sel,
            max_items=5,
            with_detail=detail_sel is not None,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"refresh failed: {e}") from e

    fetched = len(records)
    added = 0
    for r in records:
        existing = (
            await db.execute(
                select(NewsItemRow).where(
                    NewsItemRow.subscription_id == sub.id,
                    NewsItemRow.url == r.url,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            continue
        d = r.detail
        db.add(
            NewsItemRow(
                subscription_id=sub.id,
                url=r.url,
                title=r.title,
                pub_date=r.date or (d.date if d else None),
                source=(d.source if d else None),
                content=(d.content if d else ""),
            )
        )
        added += 1
    sub.last_refreshed_at = datetime.now(timezone.utc)
    await db.commit()
    return RefreshOut(added=added, fetched=fetched)


@app.get("/subscriptions/{sub_id}/news", response_model=list[NewsItemOut])
async def list_subscription_news(
    sub_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_session),
) -> list[NewsItemOut]:
    sub = await db.get(Subscription, sub_id)
    if sub is None:
        raise HTTPException(status_code=404, detail="subscription not found")
    rows = (
        (
            await db.execute(
                select(NewsItemRow)
                .where(NewsItemRow.subscription_id == sub_id)
                .order_by(NewsItemRow.fetched_at.desc(), NewsItemRow.id.desc())
                .limit(limit)
                .offset(offset)
            )
        )
        .scalars()
        .all()
    )
    return [
        NewsItemOut(
            id=n.id,
            subscription_id=n.subscription_id,
            url=n.url,
            title=n.title,
            pub_date=n.pub_date,
            source=n.source,
            fetched_at=n.fetched_at,
        )
        for n in rows
    ]


# ===== news =====


@app.get("/news/{news_id}", response_model=NewsItemDetailOut)
async def get_news(
    news_id: int, db: AsyncSession = Depends(get_session)
) -> NewsItemDetailOut:
    n = await db.get(NewsItemRow, news_id)
    if n is None:
        raise HTTPException(status_code=404, detail="news item not found")
    return NewsItemDetailOut(
        id=n.id,
        subscription_id=n.subscription_id,
        url=n.url,
        title=n.title,
        pub_date=n.pub_date,
        source=n.source,
        content=n.content,
        fetched_at=n.fetched_at,
    )


# ===== legacy direct extraction =====


@app.post("/extract")
def extract_endpoint(req: ExtractRequest) -> dict[str, Any]:
    try:
        if req.with_detail:
            records = extract_news(
                req.url, req.section, with_detail=True, max_items=req.max_items
            )
            return {"count": len(records), "items": [r.model_dump() for r in records]}
        items = extract_list_only(req.url, req.section, max_items=req.max_items)
        return {"count": len(items), "items": [i.model_dump() for i in items]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.get("/detail")
def detail_endpoint(url: str) -> dict[str, Any]:
    try:
        return extract_detail(url).model_dump()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
