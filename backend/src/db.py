"""SQLite + SQLAlchemy 2.0 async DB layer.

Tables:
- subscriptions: 订阅 = alias 唯一,持久化抓取规则 JSON;auto_enabled 控制自动化抓取
- news_items: 自动化抓取持久化条目,(subscription_id, url) 唯一
- news_items_preview: 订阅管理 tab 预览,每订阅最多 5 行,刷新覆盖
- chat_sessions: 智能体会话元数据,messages 实际由 LangGraph checkpointer 落盘;
  partial unique index 保证一个订阅至多一个 confirmed session
- app_settings: 单行 (id=1) 自动化抓取参数(触发时间/间隔/新订阅策略)
- fetch_tasks: 自动化任务队列 + 历史

Schema 演进走 Alembic(backend/alembic/versions/)。`init_db()` 启动时:
- 全新库 → alembic upgrade head
- 已有项目表但没 alembic_version(老库)→ stamp head 把现状当作初始版本,然后 upgrade head
- 已 stamp 过 → 普通 upgrade head 应用未跑过的迁移
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
    inspect,
    text,
)
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from .config import DATA_DIR


DB_PATH = DATA_DIR / "app.db"
DB_URL = f"sqlite+aiosqlite:///{DB_PATH}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    alias: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    section: Mapped[str] = mapped_column(String(255), nullable=False)
    list_selectors_json: Mapped[str] = mapped_column(Text, nullable=False)
    detail_selectors_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    auto_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(default=_now)
    updated_at: Mapped[datetime] = mapped_column(default=_now, onupdate=_now)
    last_refreshed_at: Mapped[datetime | None] = mapped_column(default=None)

    news_items: Mapped[list[NewsItemRow]] = relationship(
        back_populates="subscription",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class NewsItemRow(Base):
    __tablename__ = "news_items"
    __table_args__ = (
        UniqueConstraint("subscription_id", "url", name="uq_news_sub_url"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    subscription_id: Mapped[str] = mapped_column(
        ForeignKey("subscriptions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    pub_date: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source: Mapped[str | None] = mapped_column(String(255), nullable=True)
    content: Mapped[str] = mapped_column(Text, default="")
    fetched_at: Mapped[datetime] = mapped_column(default=_now)

    subscription: Mapped[Subscription] = relationship(back_populates="news_items")


class ChatSession(Base):
    __tablename__ = "chat_sessions"
    __table_args__ = (
        Index(
            "uq_chat_sessions_sub_confirmed",
            "subscription_id",
            unique=True,
            sqlite_where=text("status='confirmed' AND subscription_id IS NOT NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    alias: Mapped[str] = mapped_column(String(255), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    section: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="draft")
    # Draft 期间智能体学到的选择器,confirm 时复制到 subscriptions。
    # 结构与文件 cache 一致:dict[cache_key, selector_dict]。
    list_selectors_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    detail_selectors_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    subscription_id: Mapped[str | None] = mapped_column(
        ForeignKey("subscriptions.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(default=_now)
    updated_at: Mapped[datetime] = mapped_column(default=_now, onupdate=_now)


class NewsItemPreviewRow(Base):
    """订阅管理 tab 用的预览表:每个订阅最多 5 条,刷新即覆盖。

    与持久化的 news_items 平行,字段一致。覆盖逻辑由 API 在事务里 DELETE+INSERT。
    """

    __tablename__ = "news_items_preview"
    __table_args__ = (
        UniqueConstraint("subscription_id", "url", name="uq_news_preview_sub_url"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    subscription_id: Mapped[str] = mapped_column(
        ForeignKey("subscriptions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    pub_date: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source: Mapped[str | None] = mapped_column(String(255), nullable=True)
    content: Mapped[str] = mapped_column(Text, default="")
    fetched_at: Mapped[datetime] = mapped_column(default=_now)


class AppSettings(Base):
    """单行 (id=1) 的应用设置,自动化抓取参数。"""

    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(primary_key=True)  # 永远是 1
    trigger_time: Mapped[str] = mapped_column(String(5), default="09:00")  # "HH:MM" 仅 :00/:30
    interval_hours: Mapped[int] = mapped_column(Integer, default=24)  # 12 or 24
    new_sub_strategy: Mapped[str] = mapped_column(
        String(16), default="first_n"
    )  # 'first_n' | 'since_days'
    new_sub_n: Mapped[int] = mapped_column(Integer, default=20)
    last_auto_run_at: Mapped[datetime | None] = mapped_column(default=None)
    updated_at: Mapped[datetime] = mapped_column(default=_now, onupdate=_now)


class FetchTask(Base):
    """自动化抓取任务队列 + 历史记录合一表。"""

    __tablename__ = "fetch_tasks"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    subscription_id: Mapped[str] = mapped_column(
        ForeignKey("subscriptions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(
        String(16), default="pending"
    )  # 'pending' | 'running' | 'succeeded' | 'failed'
    source: Mapped[str] = mapped_column(String(8), nullable=False)  # 'manual' | 'auto'
    enqueued_at: Mapped[datetime] = mapped_column(default=_now, index=True)
    started_at: Mapped[datetime | None] = mapped_column(default=None)
    finished_at: Mapped[datetime | None] = mapped_column(default=None)
    items_added: Mapped[int | None] = mapped_column(Integer, default=None)
    items_fetched: Mapped[int | None] = mapped_column(Integer, default=None)
    pages_fetched: Mapped[int | None] = mapped_column(Integer, default=None)
    stop_reason: Mapped[str | None] = mapped_column(String(32), default=None)
    error: Mapped[str | None] = mapped_column(Text, default=None)


_engine = create_async_engine(DB_URL, echo=False, future=True)
SessionLocal = async_sessionmaker(_engine, expire_on_commit=False, class_=AsyncSession)


@event.listens_for(_engine.sync_engine, "connect")
def _enable_sqlite_pragmas(dbapi_conn: Any, _record: Any) -> None:
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


async def init_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    # 应用 Alembic 迁移到最新版本。三种情况:
    #   1) DB 文件不存在 / 完全空 → upgrade head 创建所有表
    #   2) DB 已有项目表但没 alembic_version(早期 create_all 留下的库)→
    #      先 stamp head 把现状当作 initial,再 upgrade head 应用后续迁移
    #   3) 已 stamp 过 → 普通 upgrade head
    await _run_migrations()
    # Seed singleton AppSettings row if missing.
    async with SessionLocal() as session:
        existing = await session.get(AppSettings, 1)
        if existing is None:
            session.add(AppSettings(id=1))
            await session.commit()


def _run_alembic_sync() -> None:
    """Synchronous body of the migration step. Called from a thread because
    Alembic's command API is sync; running it inside the async engine context
    would deadlock SQLite WAL.
    """
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine

    backend_root = Path(__file__).resolve().parents[1]
    cfg = Config(str(backend_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_root / "alembic"))

    sync_url = f"sqlite:///{DB_PATH}"
    sync_engine = create_engine(sync_url)
    try:
        with sync_engine.connect() as conn:
            insp = inspect(conn)
            existing = set(insp.get_table_names())
            has_version = "alembic_version" in existing
            project_tables = {
                "subscriptions",
                "news_items",
                "news_items_preview",
                "chat_sessions",
                "app_settings",
                "fetch_tasks",
            }
            legacy_pre_alembic = (not has_version) and bool(existing & project_tables)
            if legacy_pre_alembic:
                # 老库已有完整 schema,但没经过 alembic。把它标记为已经在最新
                # 已知 head;后续真正的迁移再增量 upgrade。
                command.stamp(cfg, "head")
        # 正常 upgrade,fresh 情况下从 0 跑到 head;legacy 情况下因为 stamp 已是
        # head,upgrade 是 no-op;后续新加迁移则在这里被应用。
        command.upgrade(cfg, "head")
    finally:
        sync_engine.dispose()


async def _run_migrations() -> None:
    import asyncio

    await asyncio.to_thread(_run_alembic_sync)


async def dispose_db() -> None:
    """Release the SQLAlchemy async engine's connection pool.

    Without this the WAL file can't checkpoint on shutdown because pooled
    connections are still considered live; lifespan calls this on exit.
    """
    await _engine.dispose()


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session
