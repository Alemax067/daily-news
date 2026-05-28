from __future__ import annotations

import json
from threading import Lock
from typing import Any
from urllib.parse import urlparse

from .config import SELECTOR_CACHE_PATH
from .models import DetailSelectors, ListSelectors


_lock = Lock()


def _load_raw() -> dict[str, Any]:
    if not SELECTOR_CACHE_PATH.exists():
        return {}
    try:
        with SELECTOR_CACHE_PATH.open("r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError:
        return {}


def _save_raw(data: dict[str, Any]) -> None:
    SELECTOR_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = SELECTOR_CACHE_PATH.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(SELECTOR_CACHE_PATH)


def list_key(url: str, section: str) -> str:
    p = urlparse(url)
    path = p.path or "/"
    return f"list::{p.netloc}{path}::{section.strip()}"


def detail_key(url: str) -> str:
    p = urlparse(url)
    return f"detail::{p.netloc}"


def get_list_selectors(url: str, section: str) -> ListSelectors | None:
    with _lock:
        raw = _load_raw().get(list_key(url, section))
    return ListSelectors.model_validate(raw) if raw else None


def set_list_selectors(url: str, section: str, sel: ListSelectors) -> None:
    with _lock:
        data = _load_raw()
        data[list_key(url, section)] = sel.model_dump()
        _save_raw(data)


def get_detail_selectors(url: str) -> DetailSelectors | None:
    with _lock:
        raw = _load_raw().get(detail_key(url))
    return DetailSelectors.model_validate(raw) if raw else None


def set_detail_selectors(url: str, sel: DetailSelectors) -> None:
    with _lock:
        data = _load_raw()
        data[detail_key(url)] = sel.model_dump()
        _save_raw(data)


def clear(prefix: str | None = None) -> int:
    """Drop entries; if prefix given, only matching keys (substring match)."""
    with _lock:
        data = _load_raw()
        if prefix is None:
            count = len(data)
            data = {}
        else:
            keys_to_drop = [k for k in data if prefix in k]
            count = len(keys_to_drop)
            for k in keys_to_drop:
                del data[k]
        _save_raw(data)
    return count
