"""Selector cache.

Two backends, switched per-call via a ContextVar:

- FileCacheStore (default):  data/selectors.json — used by the CLI REPL and
  any code path that hasn't opted into a session scope.
- SessionDBCacheStore:       chat_sessions.{list,detail}_selectors_json — used
  during HTTP-driven draft conversations so two concurrent drafts on the same
  (url, section) but different aliases can't clobber each other.

The HTTP message handler enters a `session_store(session_id)` context before
invoking the agent; sync tools running in worker threads inherit the
ContextVar and read/write the session's row instead of the global file.
"""

from __future__ import annotations

import json
import sqlite3
from abc import ABC, abstractmethod
from contextlib import contextmanager
from contextvars import ContextVar
from threading import Lock
from typing import Any, Iterator
from urllib.parse import urlparse

from .config import SELECTOR_CACHE_PATH
from .models import DetailSelectors, ListSelectors


def list_key(url: str, section: str) -> str:
    p = urlparse(url)
    path = p.path or "/"
    return f"list::{p.netloc}{path}::{section.strip()}"


def detail_key(url: str) -> str:
    p = urlparse(url)
    return f"detail::{p.netloc}"


# ===== backends =====


class CacheStore(ABC):
    @abstractmethod
    def load(self) -> dict[str, Any]: ...

    @abstractmethod
    def save(self, data: dict[str, Any]) -> None: ...


class FileCacheStore(CacheStore):
    def __init__(self, path: Any = None) -> None:
        self.path = path if path is not None else SELECTOR_CACHE_PATH
        self._lock = Lock()

    def load(self) -> dict[str, Any]:
        with self._lock:
            if not self.path.exists():
                return {}
            try:
                with self.path.open("r", encoding="utf-8") as f:
                    return json.load(f)
            except json.JSONDecodeError:
                return {}

    def save(self, data: dict[str, Any]) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".json.tmp")
            with tmp.open("w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            tmp.replace(self.path)


class SessionDBCacheStore(CacheStore):
    """Per-chat-session selector cache backed by `chat_sessions` row.

    Uses stdlib sqlite3 (sync) — tools run in worker threads, so blocking
    is fine. The DB file is shared with SQLAlchemy under WAL mode.
    """

    def __init__(self, session_id: str, db_path: str) -> None:
        self.session_id = session_id
        self.db_path = db_path

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, isolation_level=None, timeout=5.0)
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def load(self) -> dict[str, Any]:
        conn = self._conn()
        try:
            cur = conn.execute(
                "SELECT list_selectors_json, detail_selectors_json "
                "FROM chat_sessions WHERE id = ?",
                (self.session_id,),
            )
            row = cur.fetchone()
        finally:
            conn.close()
        if row is None:
            return {}
        list_j, detail_j = row
        data: dict[str, Any] = {}
        if list_j:
            data.update(json.loads(list_j))
        if detail_j:
            data.update(json.loads(detail_j))
        return data

    def save(self, data: dict[str, Any]) -> None:
        list_d = {k: v for k, v in data.items() if k.startswith("list::")}
        detail_d = {k: v for k, v in data.items() if k.startswith("detail::")}
        conn = self._conn()
        try:
            conn.execute(
                "UPDATE chat_sessions "
                "SET list_selectors_json = ?, detail_selectors_json = ? "
                "WHERE id = ?",
                (
                    json.dumps(list_d, ensure_ascii=False) if list_d else None,
                    json.dumps(detail_d, ensure_ascii=False) if detail_d else None,
                    self.session_id,
                ),
            )
        finally:
            conn.close()


# ===== current-store ContextVar =====


_default_store: CacheStore = FileCacheStore()
_store_var: ContextVar[CacheStore] = ContextVar("cache_store", default=_default_store)


@contextmanager
def session_store(session_id: str, db_path: str) -> Iterator[CacheStore]:
    """Swap in a session-scoped cache for the duration of the with-block.

    ContextVar semantics propagate the override into worker threads spawned
    by `asyncio.to_thread` / `run_in_executor`, so sync agent tools see it.
    """
    store = SessionDBCacheStore(session_id, db_path)
    token = _store_var.set(store)
    try:
        yield store
    finally:
        _store_var.reset(token)


def _store() -> CacheStore:
    return _store_var.get()


# ===== public accessors (unchanged signatures) =====


def get_list_selectors(url: str, section: str) -> ListSelectors | None:
    raw = _store().load().get(list_key(url, section))
    return ListSelectors.model_validate(raw) if raw else None


def set_list_selectors(url: str, section: str, sel: ListSelectors) -> None:
    s = _store()
    data = s.load()
    data[list_key(url, section)] = sel.model_dump()
    s.save(data)


def get_detail_selectors(url: str) -> DetailSelectors | None:
    raw = _store().load().get(detail_key(url))
    return DetailSelectors.model_validate(raw) if raw else None


def set_detail_selectors(url: str, sel: DetailSelectors) -> None:
    s = _store()
    data = s.load()
    data[detail_key(url)] = sel.model_dump()
    s.save(data)


def clear(prefix: str | None = None) -> int:
    s = _store()
    data = s.load()
    if prefix is None:
        count = len(data)
        s.save({})
        return count
    keys_to_drop = [k for k in data if prefix in k]
    for k in keys_to_drop:
        del data[k]
    s.save(data)
    return len(keys_to_drop)
