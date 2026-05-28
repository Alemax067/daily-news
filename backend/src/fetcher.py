from __future__ import annotations

import httpx

from .config import get_settings


def fetch_html(url: str) -> str:
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
        return resp.text
