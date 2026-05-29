"""FastAPI service: subscriptions + agent sessions (SSE) + news.

Routes:
- /sessions  POST/GET/DELETE,  /sessions/{id}/messages (SSE start),
  /sessions/{id}/stream (SSE resume),  /sessions/{id}/confirm
- /subscriptions  GET/DELETE,
  /subscriptions/{id}/refresh-preview,  /subscriptions/{id}/preview-news,
  /subscriptions/{id}/session,  /subscriptions/{id}/update-from-session,
  /subscriptions/{id}/news
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
import re
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
from . import scheduler
from .agent import build_agent
from .db import (
    DB_PATH,
    AppSettings,
    ChatSession,
    FetchTask,
    NewsItemPreviewRow,
    NewsItemRow,
    SessionLocal,
    Subscription,
    dispose_db,
    get_session,
    init_db,
)
from .extractor import extract_detail, extract_list_only, extract_news
from .fetcher import clear_fetch_cache
from .models import (
    AppSettingsIn,
    AppSettingsOut,
    ChatMessageOut,
    DetailSelectors,
    ExtractRequest,
    FetchTaskOut,
    ListSelectors,
    NewsItemDetailOut,
    NewsItemOut,
    QueueSnapshotOut,
    RefreshOut,
    SessionConfirmOut,
    SessionCreateIn,
    SessionCreateOut,
    SessionLookupOut,
    SessionMessageIn,
    SessionOut,
    SubscriptionDetailOut,
    SubscriptionOut,
    SubscriptionPatchIn,
    TriggerAutomationOut,
    UpdateFromSessionIn,
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
        # 启动恢复 + 后台任务
        await scheduler.recover_on_startup(_state)
        scheduler.start_background(_state)
        try:
            yield
        finally:
            # 0. 先停后台任务,避免 worker 在 shutdown 期间继续打 DB
            await scheduler.stop_background(_state)
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


def _sub_to_out(
    s: Subscription,
    item_count: int = 0,
    preview_item_count: int = 0,
    preview_refreshed_at: datetime | None = None,
) -> SubscriptionOut:
    return SubscriptionOut(
        id=s.id,
        alias=s.alias,
        url=s.url,
        section=s.section,
        auto_enabled=s.auto_enabled,
        last_refreshed_at=s.last_refreshed_at,
        item_count=item_count,
        preview_refreshed_at=preview_refreshed_at,
        preview_item_count=preview_item_count,
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


@app.get("/health")
async def health() -> dict[str, str]:
    """Liveness probe used by `npm run dev` to wait until backend is ready."""
    return {"status": "ok"}


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
    if sess.status not in ("draft", "confirmed"):
        raise HTTPException(status_code=409, detail=f"session is {sess.status}")

    if _is_streaming(session_id):
        raise HTTPException(
            status_code=409, detail="智能体正在回复中,请等当前轮结束再发送"
        )

    # Replace any prior completed run for this session.
    _streams.pop(session_id, None)

    agent = _agent()
    config = {"configurable": {"thread_id": session_id}, "recursion_limit": 500}
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
    auto_cnt = (
        select(
            NewsItemRow.subscription_id.label("sid"),
            func.count(NewsItemRow.id).label("cnt"),
        )
        .group_by(NewsItemRow.subscription_id)
        .subquery()
    )
    prev_agg = (
        select(
            NewsItemPreviewRow.subscription_id.label("sid"),
            func.count(NewsItemPreviewRow.id).label("cnt"),
            func.max(NewsItemPreviewRow.fetched_at).label("max_fetched"),
        )
        .group_by(NewsItemPreviewRow.subscription_id)
        .subquery()
    )
    rows = (
        await db.execute(
            select(
                Subscription,
                func.coalesce(auto_cnt.c.cnt, 0).label("auto_cnt"),
                func.coalesce(prev_agg.c.cnt, 0).label("prev_cnt"),
                prev_agg.c.max_fetched.label("prev_at"),
            )
            .outerjoin(auto_cnt, auto_cnt.c.sid == Subscription.id)
            .outerjoin(prev_agg, prev_agg.c.sid == Subscription.id)
            .order_by(Subscription.created_at.desc())
        )
    ).all()
    return [
        _sub_to_out(
            s,
            item_count=int(auto_cnt_v),
            preview_item_count=int(prev_cnt_v),
            preview_refreshed_at=prev_at_v,
        )
        for s, auto_cnt_v, prev_cnt_v, prev_at_v in rows
    ]


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
    prev_cnt = (
        await db.execute(
            select(func.count(NewsItemPreviewRow.id)).where(
                NewsItemPreviewRow.subscription_id == sub.id
            )
        )
    ).scalar_one()
    prev_at = (
        await db.execute(
            select(func.max(NewsItemPreviewRow.fetched_at)).where(
                NewsItemPreviewRow.subscription_id == sub.id
            )
        )
    ).scalar_one()
    return SubscriptionDetailOut(
        id=sub.id,
        alias=sub.alias,
        url=sub.url,
        section=sub.section,
        auto_enabled=sub.auto_enabled,
        created_at=sub.created_at,
        last_refreshed_at=sub.last_refreshed_at,
        item_count=cnt,
        preview_refreshed_at=prev_at,
        preview_item_count=prev_cnt,
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


@app.post("/subscriptions/{sub_id}/refresh-preview", response_model=RefreshOut)
async def refresh_subscription_preview(
    sub_id: str, db: AsyncSession = Depends(get_session)
) -> RefreshOut:
    """订阅管理 tab 用:抓最新 5 条到 news_items_preview,DELETE+INSERT 覆盖。"""
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

    # 覆盖式:先清空该 sub 的预览行,再批量 INSERT。
    await db.execute(
        NewsItemPreviewRow.__table__.delete().where(
            NewsItemPreviewRow.subscription_id == sub_id
        )
    )
    fetched = len(records)
    for r in records:
        d = r.detail
        db.add(
            NewsItemPreviewRow(
                subscription_id=sub.id,
                url=r.url,
                title=r.title,
                pub_date=r.date or (d.date if d else None),
                source=(d.source if d else None),
                content=(d.content if d else ""),
            )
        )
    await db.commit()
    return RefreshOut(added=fetched, fetched=fetched)


@app.get("/subscriptions/{sub_id}/preview-news", response_model=list[NewsItemOut])
async def list_subscription_preview_news(
    sub_id: str, db: AsyncSession = Depends(get_session)
) -> list[NewsItemOut]:
    sub = await db.get(Subscription, sub_id)
    if sub is None:
        raise HTTPException(status_code=404, detail="subscription not found")
    # NULL pub_date 用 fetched_at 字符串补位,与有日期的混排。
    sort_key = func.coalesce(
        NewsItemPreviewRow.pub_date,
        func.strftime("%Y-%m-%d %H:%M:%S", NewsItemPreviewRow.fetched_at),
    )
    rows = (
        (
            await db.execute(
                select(NewsItemPreviewRow)
                .where(NewsItemPreviewRow.subscription_id == sub_id)
                .order_by(
                    sort_key.desc(),
                    NewsItemPreviewRow.id.asc(),
                )
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


@app.get("/subscriptions/{sub_id}/session", response_model=SessionLookupOut)
async def get_subscription_session(
    sub_id: str, db: AsyncSession = Depends(get_session)
) -> SessionLookupOut:
    """订阅管理 reopen:返回该订阅唯一一个 confirmed session(由 partial unique index 保证唯一)。"""
    sub = await db.get(Subscription, sub_id)
    if sub is None:
        raise HTTPException(status_code=404, detail="subscription not found")
    sess = (
        await db.execute(
            select(ChatSession).where(
                ChatSession.subscription_id == sub_id,
                ChatSession.status == "confirmed",
            )
        )
    ).scalar_one_or_none()
    return SessionLookupOut(session_id=sess.id if sess else None)


@app.post("/subscriptions/{sub_id}/update-from-session")
async def update_subscription_from_session(
    sub_id: str,
    body: UpdateFromSessionIn,
    db: AsyncSession = Depends(get_session),
) -> dict[str, bool]:
    """订阅管理 reopen 后,把 session 当前学到的 selectors 覆盖回 subscription。

    沿用 confirm 的两个闸门:
      - list + detail 必须都已学到
      - 不允许在流式回复中操作
    """
    sub = await db.get(Subscription, sub_id)
    if sub is None:
        raise HTTPException(status_code=404, detail="subscription not found")
    sess = await db.get(ChatSession, body.session_id)
    if sess is None:
        raise HTTPException(status_code=404, detail="session not found")
    if sess.subscription_id != sub_id or sess.status != "confirmed":
        raise HTTPException(
            status_code=409, detail="session 不属于此订阅或不是 confirmed 状态"
        )
    if _is_streaming(sess.id):
        raise HTTPException(
            status_code=409, detail="智能体正在回复中,请等回复完成再更新"
        )

    list_sel: ListSelectors | None = None
    if sess.list_selectors_json:
        cache_dict = json.loads(sess.list_selectors_json)
        raw = cache_dict.get(cache_mod.list_key(sess.url, sess.section))
        if raw:
            list_sel = ListSelectors.model_validate(raw)
    if list_sel is None:
        raise HTTPException(
            status_code=400, detail="session 中暂无可用 list 选择器,请继续对话"
        )
    detail_sel: DetailSelectors | None = None
    if sess.detail_selectors_json:
        cache_dict = json.loads(sess.detail_selectors_json)
        raw = cache_dict.get(cache_mod.detail_key(sess.url))
        if raw:
            detail_sel = DetailSelectors.model_validate(raw)
    if detail_sel is None:
        raise HTTPException(
            status_code=400, detail="session 中暂无可用 detail 选择器,请继续对话"
        )

    sub.list_selectors_json = list_sel.model_dump_json()
    sub.detail_selectors_json = detail_sel.model_dump_json()
    await db.commit()
    return {"ok": True}


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
    sort_key = func.coalesce(
        NewsItemRow.pub_date,
        func.strftime("%Y-%m-%d %H:%M:%S", NewsItemRow.fetched_at),
    )
    rows = (
        (
            await db.execute(
                select(NewsItemRow)
                .where(NewsItemRow.subscription_id == sub_id)
                .order_by(
                    sort_key.desc(),
                    NewsItemRow.id.asc(),
                )
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


# ===== automation: per-subscription patch + tasks =====


_TRIGGER_TIME_RE = re.compile(r"^([01]\d|2[0-3]):(00|30)$")


def _queue_event() -> asyncio.Event:
    """Lazily create the shared asyncio.Event used to wake SSE subscribers
    when fetch_tasks status changes. Scheduler calls .set() on transitions.
    """
    ev = _state.get("queue_event")
    if ev is None:
        ev = asyncio.Event()
        _state["queue_event"] = ev
    return ev


def _settings_event() -> asyncio.Event:
    """Used to nudge scheduler_loop when settings change."""
    ev = _state.get("settings_event")
    if ev is None:
        ev = asyncio.Event()
        _state["settings_event"] = ev
    return ev


def _task_to_out(task: FetchTask, alias: str | None = None) -> FetchTaskOut:
    return FetchTaskOut(
        id=task.id,
        subscription_id=task.subscription_id,
        subscription_alias=alias,
        status=task.status,  # type: ignore[arg-type]
        source=task.source,  # type: ignore[arg-type]
        enqueued_at=task.enqueued_at,
        started_at=task.started_at,
        finished_at=task.finished_at,
        items_added=task.items_added,
        items_fetched=task.items_fetched,
        pages_fetched=task.pages_fetched,
        stop_reason=task.stop_reason,
        error=task.error,
    )


async def _build_queue_snapshot(db: AsyncSession) -> QueueSnapshotOut:
    """Snapshot for /automation/queue and SSE: running + pending + recent_done."""
    # 并行三条查询用 SELECT ... JOIN subscriptions 拿 alias
    running_row = (
        await db.execute(
            select(FetchTask, Subscription.alias)
            .join(Subscription, Subscription.id == FetchTask.subscription_id)
            .where(FetchTask.status == "running")
            .order_by(FetchTask.started_at.desc())
            .limit(1)
        )
    ).first()
    pending_rows = (
        await db.execute(
            select(FetchTask, Subscription.alias)
            .join(Subscription, Subscription.id == FetchTask.subscription_id)
            .where(FetchTask.status == "pending")
            .order_by(FetchTask.enqueued_at.asc())
        )
    ).all()
    done_rows = (
        await db.execute(
            select(FetchTask, Subscription.alias)
            .join(Subscription, Subscription.id == FetchTask.subscription_id)
            .where(FetchTask.status.in_(["succeeded", "failed"]))
            .order_by(FetchTask.finished_at.desc())
            .limit(20)
        )
    ).all()
    return QueueSnapshotOut(
        running=_task_to_out(running_row[0], running_row[1]) if running_row else None,
        pending=[_task_to_out(t, a) for t, a in pending_rows],
        recent_done=[_task_to_out(t, a) for t, a in done_rows],
    )


@app.patch("/subscriptions/{sub_id}", response_model=SubscriptionOut)
async def patch_subscription(
    sub_id: str,
    body: SubscriptionPatchIn,
    db: AsyncSession = Depends(get_session),
) -> SubscriptionOut:
    sub = await db.get(Subscription, sub_id)
    if sub is None:
        raise HTTPException(status_code=404, detail="subscription not found")
    sub.auto_enabled = body.auto_enabled
    await db.commit()
    cnt = (
        await db.execute(
            select(func.count(NewsItemRow.id)).where(NewsItemRow.subscription_id == sub.id)
        )
    ).scalar_one()
    return _sub_to_out(sub, cnt)


@app.get("/subscriptions/{sub_id}/tasks", response_model=list[FetchTaskOut])
async def list_subscription_tasks(
    sub_id: str,
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_session),
) -> list[FetchTaskOut]:
    sub = await db.get(Subscription, sub_id)
    if sub is None:
        raise HTTPException(status_code=404, detail="subscription not found")
    rows = (
        (
            await db.execute(
                select(FetchTask)
                .where(FetchTask.subscription_id == sub_id)
                .order_by(FetchTask.enqueued_at.desc(), FetchTask.id.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return [_task_to_out(t, sub.alias) for t in rows]


# ===== automation: settings =====


def _validate_settings(body: AppSettingsIn) -> str | None:
    if not _TRIGGER_TIME_RE.match(body.trigger_time):
        return "trigger_time 必须形如 HH:MM 且分钟为 :00 或 :30"
    if body.interval_hours not in (12, 24):
        return "interval_hours 必须是 12 或 24"
    if body.new_sub_strategy == "first_n" and not (1 <= body.new_sub_n <= 100):
        return "first_n 模式下 new_sub_n 必须在 1..100"
    if body.new_sub_strategy == "since_days" and not (1 <= body.new_sub_n <= 90):
        return "since_days 模式下 new_sub_n 必须在 1..90"
    return None


@app.get("/automation/settings", response_model=AppSettingsOut)
async def get_automation_settings(
    db: AsyncSession = Depends(get_session),
) -> AppSettingsOut:
    s = await db.get(AppSettings, 1)
    if s is None:
        raise HTTPException(status_code=500, detail="settings row missing; init_db 应保证有")
    return AppSettingsOut(
        trigger_time=s.trigger_time,
        interval_hours=s.interval_hours,
        new_sub_strategy=s.new_sub_strategy,  # type: ignore[arg-type]
        new_sub_n=s.new_sub_n,
        last_auto_run_at=s.last_auto_run_at,
    )


@app.put("/automation/settings", response_model=AppSettingsOut)
async def set_automation_settings(
    body: AppSettingsIn,
    db: AsyncSession = Depends(get_session),
) -> AppSettingsOut:
    err = _validate_settings(body)
    if err is not None:
        raise HTTPException(status_code=400, detail=err)
    s = await db.get(AppSettings, 1)
    if s is None:
        raise HTTPException(status_code=500, detail="settings row missing; init_db 应保证有")
    s.trigger_time = body.trigger_time
    s.interval_hours = body.interval_hours
    s.new_sub_strategy = body.new_sub_strategy
    s.new_sub_n = body.new_sub_n
    await db.commit()
    # 通知调度循环重新计算下次 fire 时间
    _settings_event().set()
    return AppSettingsOut(
        trigger_time=s.trigger_time,
        interval_hours=s.interval_hours,
        new_sub_strategy=s.new_sub_strategy,  # type: ignore[arg-type]
        new_sub_n=s.new_sub_n,
        last_auto_run_at=s.last_auto_run_at,
    )


# ===== automation: trigger + queue =====


@app.post("/automation/trigger", response_model=TriggerAutomationOut)
async def trigger_automation(
    db: AsyncSession = Depends(get_session),
) -> TriggerAutomationOut:
    """手动触发一轮:把所有 auto_enabled=True 的订阅入队,source='manual'。"""
    rows = (
        (
            await db.execute(
                select(Subscription.id).where(Subscription.auto_enabled.is_(True))
            )
        )
        .scalars()
        .all()
    )
    for sid in rows:
        db.add(FetchTask(subscription_id=sid, status="pending", source="manual"))
    await db.commit()
    if rows:
        _queue_event().set()
    return TriggerAutomationOut(enqueued=len(rows))


@app.get("/automation/queue", response_model=QueueSnapshotOut)
async def get_queue_snapshot(
    db: AsyncSession = Depends(get_session),
) -> QueueSnapshotOut:
    return await _build_queue_snapshot(db)


@app.get("/automation/queue/stream")
async def stream_queue() -> StreamingResponse:
    """SSE: 推送队列状态快照。worker 每次状态翻转 set queue_event,这里 wait 后重新查 DB 推送。"""

    async def gen() -> AsyncIterator[str]:
        ev = _queue_event()
        async with SessionLocal() as db:
            snap = await _build_queue_snapshot(db)
        yield _sse("snapshot", snap.model_dump(mode="json"))
        while True:
            try:
                await asyncio.wait_for(ev.wait(), timeout=5.0)
                ev.clear()
            except asyncio.TimeoutError:
                # 5s heartbeat-cum-poll,兜底防漏推
                pass
            async with SessionLocal() as db:
                snap = await _build_queue_snapshot(db)
            yield _sse("snapshot", snap.model_dump(mode="json"))

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
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
