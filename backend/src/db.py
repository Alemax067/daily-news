"""SQLite + SQLAlchemy 2.0 async DB layer.

Tables:
- subscriptions: 订阅 = alias 唯一,持久化抓取规则 JSON
- news_items: 每个订阅下抓到的新闻条目,(subscription_id, url) 唯一
- chat_sessions: 智能体会话元数据,messages 实际由 LangGraph checkpointer 落盘
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint, event
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
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session
