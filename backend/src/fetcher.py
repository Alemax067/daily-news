from __future__ import annotations

import threading
import time
from typing import Any
from urllib.parse import urljoin

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


def fetch_json(
    endpoint: str,
    method: str = "POST",
    body: dict[str, str] | None = None,
    *,
    base_url: str | None = None,
    referer: str | None = None,
) -> Any:
    """Hit a JSON API and return parsed dict/list. No caching (paginated bodies vary).

    Args:
        endpoint: 完整 URL 或相对路径(配合 base_url 走 urljoin)。
        method: GET 或 POST(大小写不敏感)。
        body: 请求体字段。POST 用 application/x-www-form-urlencoded(jQuery 默认),
            GET 作为 query params。jQuery 嵌套写法直接展平到 dict,
            如 {'datas[0][key]': 'status'}。
        base_url: 当 endpoint 是相对路径时拼接的基地址(列表页 URL)。
        referer: 可选 Referer 头,部分 gov API 校验 Referer。
    """
    if base_url is not None:
        endpoint = urljoin(base_url, endpoint)
    settings = get_settings()
    headers = {
        "User-Agent": settings.fetch_user_agent,
        "Accept": "application/json,text/plain,*/*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "X-Requested-With": "XMLHttpRequest",
    }
    if referer:
        headers["Referer"] = referer
    elif base_url:
        headers["Referer"] = base_url

    with httpx.Client(
        headers=headers,
        timeout=settings.fetch_timeout,
        follow_redirects=True,
        verify=False,
    ) as client:
        m = method.upper()
        if m == "GET":
            resp = client.get(endpoint, params=body or {})
        elif m == "POST":
            resp = client.post(endpoint, data=body or {})
        else:
            raise ValueError(f"unsupported method: {method!r}; only GET / POST")
        resp.raise_for_status()
        return resp.json()
