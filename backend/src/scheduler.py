"""Automation scheduler + serial fetch-task worker.

Two long-running asyncio tasks owned by the FastAPI lifespan:

- queue_worker: pops fetch_tasks rows where status='pending', runs the actual
  paginated extract for that subscription, INSERTs records into news_items
  (UNIQUE-deduped), and writes back items_added/items_fetched/pages_fetched/
  stop_reason. Sets `_state['queue_event']` on every status transition so
  /automation/queue/stream subscribers wake up.

- scheduler_loop: reads app_settings, computes next fire time
  (trigger_time + interval_hours), sleeps until then (interruptible via
  `_state['settings_event']`), enqueues all auto_enabled subscriptions with
  source='auto', writes last_auto_run_at, and loops.

Startup recovery (called from lifespan before workers start):
  1. UPDATE fetch_tasks SET status='pending' WHERE status='running' — leftover
     from a crash; uniqueness on (subscription_id, url) lets a re-run be safe.
  2. If now - last_auto_run_at > interval_hours, enqueue an auto run
     immediately. Only one catch-up; we don't replay every missed fire.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from . import extractor
from .db import (
    AppSettings,
    FetchTask,
    NewsItemRow,
    SessionLocal,
    Subscription,
)
from .models import DetailSelectors, ListSelectors


log = logging.getLogger(__name__)


# ===== queue worker =====


async def _claim_one_pending(db: AsyncSession) -> FetchTask | None:
    """Pop the oldest pending task and mark it running atomically.

    Single-worker design means there's no contention, but we still gate the
    UPDATE on status='pending' so a manual SQL poke can't accidentally
    double-run it.
    """
    row = (
        await db.execute(
            select(FetchTask)
            .where(FetchTask.status == "pending")
            .order_by(FetchTask.enqueued_at.asc(), FetchTask.id.asc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    result = await db.execute(
        update(FetchTask)
        .where(FetchTask.id == row.id, FetchTask.status == "pending")
        .values(status="running", started_at=datetime.now(timezone.utc))
    )
    if result.rowcount == 0:
        await db.rollback()
        return None
    await db.commit()
    await db.refresh(row)
    return row


async def _existing_urls(db: AsyncSession, sub_id: str) -> set[str]:
    rows = (
        await db.execute(
            select(NewsItemRow.url).where(NewsItemRow.subscription_id == sub_id)
        )
    ).scalars().all()
    return set(rows)


async def _is_new_subscription(db: AsyncSession, sub_id: str) -> bool:
    cnt = (
        await db.execute(
            select(NewsItemRow.id).where(NewsItemRow.subscription_id == sub_id).limit(1)
        )
    ).scalar_one_or_none()
    return cnt is None


async def _run_one_task(state: dict[str, Any], task_id: int) -> None:
    """Execute a single fetch task end-to-end. Errors get written to task row."""
    queue_event: asyncio.Event = state["queue_event"]

    async with SessionLocal() as db:
        task = await db.get(FetchTask, task_id)
        if task is None:
            return
        sub = await db.get(Subscription, task.subscription_id)
        if sub is None:
            task.status = "failed"
            task.error = "subscription not found"
            task.finished_at = datetime.now(timezone.utc)
            await db.commit()
            queue_event.set()
            return

        list_sel = ListSelectors.model_validate_json(sub.list_selectors_json)
        detail_sel: DetailSelectors | None = (
            DetailSelectors.model_validate_json(sub.detail_selectors_json)
            if sub.detail_selectors_json
            else None
        )

        settings = await db.get(AppSettings, 1)
        is_new = await _is_new_subscription(db, sub.id)
        if is_new:
            mode = settings.new_sub_strategy if settings else "first_n"
            n = settings.new_sub_n if settings else 20
            existing_urls = None
        else:
            mode = "incremental"
            n = None
            existing_urls = await _existing_urls(db, sub.id)

    # 抓取在 thread 里跑(fetch_html 阻塞 socket)。注意:出 SessionLocal 后再调,
    # 避免长时间持有 DB 连接。
    try:
        result = await asyncio.to_thread(
            extractor.extract_paginated,
            url=sub.url,
            list_selectors=list_sel,
            detail_selectors=detail_sel,
            mode=mode,  # type: ignore[arg-type]
            n=n,
            existing_urls=existing_urls,
            max_pages=5,
            max_items=100,
            with_detail=detail_sel is not None,
        )
    except Exception as e:
        log.exception("fetch task %s failed", task_id)
        async with SessionLocal() as db:
            t = await db.get(FetchTask, task_id)
            if t is not None:
                t.status = "failed"
                t.error = str(e)[:2000]
                t.finished_at = datetime.now(timezone.utc)
                await db.commit()
        queue_event.set()
        return

    # 成功:写入 news_items + 更新 task 行
    async with SessionLocal() as db:
        items_added = 0
        for r in result.records:
            d = r.detail
            stmt = (
                sqlite_insert(NewsItemRow.__table__)
                .values(
                    subscription_id=sub.id,
                    url=r.url,
                    title=r.title,
                    pub_date=r.date or (d.date if d else None),
                    source=(d.source if d else None),
                    content=(d.content if d else ""),
                    fetch_task_id=task_id,
                )
                .on_conflict_do_nothing(index_elements=["subscription_id", "url"])
            )
            res = await db.execute(stmt)
            if res.rowcount and res.rowcount > 0:
                items_added += 1

        t = await db.get(FetchTask, task_id)
        if t is not None:
            t.status = "succeeded"
            t.items_added = items_added
            t.items_fetched = len(result.records)
            t.pages_fetched = result.pages_fetched
            t.stop_reason = result.stop_reason
            t.finished_at = datetime.now(timezone.utc)

        sub_row = await db.get(Subscription, sub.id)
        if sub_row is not None:
            sub_row.last_refreshed_at = datetime.now(timezone.utc)
        await db.commit()
    queue_event.set()


async def queue_worker(state: dict[str, Any]) -> None:
    """Long-running serial worker. Cancelled by lifespan on shutdown."""
    queue_event: asyncio.Event = state.setdefault("queue_event", asyncio.Event())
    log.info("queue_worker started")
    try:
        while True:
            async with SessionLocal() as db:
                task = await _claim_one_pending(db)
            if task is None:
                # 空闲:等 queue_event(被 trigger / scheduler / 完成回调拨醒)或 2s 兜底
                try:
                    await asyncio.wait_for(queue_event.wait(), timeout=2.0)
                    queue_event.clear()
                except asyncio.TimeoutError:
                    pass
                continue
            queue_event.set()  # running 状态翻转
            await _run_one_task(state, task.id)
    except asyncio.CancelledError:
        log.info("queue_worker cancelled")
        raise


# ===== scheduler loop =====


def _next_fire_at(now: datetime, trigger_time: str, interval_hours: int) -> datetime:
    """Smallest future fire time. trigger_time is HH:MM in `now`'s timezone."""
    h, m = map(int, trigger_time.split(":"))
    cand = now.replace(hour=h, minute=m, second=0, microsecond=0)
    while cand <= now:
        cand += timedelta(hours=interval_hours)
    return cand


async def _enqueue_auto_run(state: dict[str, Any], reason: str) -> int:
    """Enqueue all auto_enabled subscriptions, source='auto'. Returns count."""
    queue_event: asyncio.Event = state.setdefault("queue_event", asyncio.Event())
    run_id = str(uuid.uuid4())
    async with SessionLocal() as db:
        sub_ids = (
            (
                await db.execute(
                    select(Subscription.id).where(Subscription.auto_enabled.is_(True))
                )
            )
            .scalars()
            .all()
        )
        for sid in sub_ids:
            db.add(FetchTask(subscription_id=sid, status="pending", source="auto", run_id=run_id))
        s = await db.get(AppSettings, 1)
        if s is not None:
            s.last_auto_run_at = datetime.now(timezone.utc)
        await db.commit()
    if sub_ids:
        queue_event.set()
    log.info("auto run enqueued %d tasks (reason=%s)", len(sub_ids), reason)
    return len(sub_ids)


async def scheduler_loop(state: dict[str, Any]) -> None:
    """Long-running scheduler. Wakes on settings_event for re-plan."""
    settings_event: asyncio.Event = state.setdefault("settings_event", asyncio.Event())
    log.info("scheduler_loop started")
    try:
        while True:
            async with SessionLocal() as db:
                s = await db.get(AppSettings, 1)
                trigger_time = s.trigger_time if s else "09:00"
                interval = s.interval_hours if s else 24

            now_local = datetime.now().astimezone()
            fire_at = _next_fire_at(now_local, trigger_time, interval)
            sleep_s = max(1.0, (fire_at - now_local).total_seconds())
            log.info("next auto fire at %s (sleep %ds)", fire_at.isoformat(), int(sleep_s))

            try:
                await asyncio.wait_for(settings_event.wait(), timeout=sleep_s)
                settings_event.clear()
                # settings changed → 重新 plan,本轮不入队
                continue
            except asyncio.TimeoutError:
                pass

            await _enqueue_auto_run(state, reason="scheduled")
    except asyncio.CancelledError:
        log.info("scheduler_loop cancelled")
        raise


# ===== startup recovery =====


async def recover_on_startup(state: dict[str, Any]) -> None:
    """Reset orphaned 'running' tasks back to 'pending', and catch up missed auto fires."""
    async with SessionLocal() as db:
        # 1. revive orphan running tasks
        await db.execute(
            update(FetchTask)
            .where(FetchTask.status == "running")
            .values(status="pending", started_at=None)
        )
        await db.commit()

        # 2. miss-fire detection
        s = await db.get(AppSettings, 1)
    if s is not None and s.last_auto_run_at is not None:
        now = datetime.now(timezone.utc)
        # last_auto_run_at 可能是 naive(SQLite 不存 tz);按 UTC 处理
        last = s.last_auto_run_at
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        if (now - last).total_seconds() > s.interval_hours * 3600:
            await _enqueue_auto_run(state, reason="startup-catchup")


# ===== lifespan helpers =====


def start_background(state: dict[str, Any]) -> None:
    """Spawn the two background tasks; store handles in `state` for shutdown."""
    state["queue_worker_task"] = asyncio.create_task(queue_worker(state))
    state["scheduler_task"] = asyncio.create_task(scheduler_loop(state))


async def stop_background(state: dict[str, Any]) -> None:
    """Cancel and await both background tasks (called from lifespan finally)."""
    for name in ("queue_worker_task", "scheduler_task"):
        t = state.get(name)
        if t is None or t.done():
            continue
        t.cancel()
        try:
            await asyncio.wait_for(t, timeout=2.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass
        state.pop(name, None)
