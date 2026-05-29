from __future__ import annotations

import threading
import time

import httpx

from .config import get_settings


_TTL_SECONDS = 300.0
_cache: dict[str, tuple[float, str]] = {}
_cache_lock = threading.Lock()


def _cache_get(url: str) -> str | None:
    with _cache_lock:
        entry = _cache.get(url)
        if entry is None:
            return None
        ts, html = entry
        if time.monotonic() - ts > _TTL_SECONDS:
            _cache.pop(url, None)
            return None
        return html


def _cache_put(url: str, html: str) -> None:
    with _cache_lock:
        _cache[url] = (time.monotonic(), html)


def clear_fetch_cache() -> int:
    """Drop all cached HTML responses. Returns count cleared."""
    with _cache_lock:
        n = len(_cache)
        _cache.clear()
    return n


def fetch_html(url: str, *, force: bool = False) -> str:
    if not force:
        cached = _cache_get(url)
        if cached is not None:
            return cached
    settings = get_settings()
    headers = {
        "User-Agent": settings.fetch_user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    with httpx.Client(
        headers=headers,
        timeout=settings.fetch_timeout,
        follow_redirects=True,
        verify=False,
    ) as client:
        resp = client.get(url)
        resp.raise_for_status()
        if not resp.encoding or resp.encoding.lower() in {"iso-8859-1", "ascii"}:
            resp.encoding = resp.charset_encoding or resp.apparent_encoding or "utf-8"
        html = resp.text
    _cache_put(url, html)
    return html
