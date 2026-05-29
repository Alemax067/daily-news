"""High-level extraction: orchestrates cache lookup → LLM learning → DOM parsing.

Public API:
    extract_news(url, section, with_detail=True, max_items=20) -> list[NewsRecord]
    extract_list_only(url, section, max_items=20) -> list[NewsItem]
    extract_detail(url) -> NewsDetail
"""

from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from . import cache
from .config import get_settings
from .fetcher import fetch_html
from .learner import learn_detail_selectors, learn_list_selectors
from .models import (
    DetailSelectors,
    ListSelectors,
    NewsDetail,
    NewsItem,
    NewsRecord,
)
from .skeleton import to_skeleton


def _select_one(scope: Tag, selector: str) -> Tag | None:
    try:
        return scope.select_one(selector)
    except Exception:
        return None


def normalize_pub_date(
    raw: str | None,
    patterns: list[str] | None,
    output: str | None,
) -> str | None:
    """Try strptime patterns in order; return ISO string on first success, else None."""
    if not raw or not patterns or not output:
        return None
    fmt_out = "%Y-%m-%d" if output == "iso_date" else "%Y-%m-%d %H:%M:%S"
    text = raw.strip()
    for pat in patterns:
        try:
            dt = datetime.strptime(text, pat)
        except ValueError:
            continue
        return dt.strftime(fmt_out)
    return None


def _extract_attr(node: Tag | None, attr: str) -> str | None:
    if node is None:
        return None
    if attr == "text":
        return re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip() or None
    val = node.get(attr)
    if isinstance(val, list):
        val = " ".join(val)
    return str(val).strip() if val else None


def _ensure_list_selectors(html: str, url: str, section: str) -> ListSelectors:
    sel = cache.get_list_selectors(url, section)
    if sel is not None:
        return sel
    settings = get_settings()
    skeleton = to_skeleton(html, max_chars=settings.list_skeleton_max_chars)
    sel = learn_list_selectors(skeleton, section, url)
    cache.set_list_selectors(url, section, sel)
    return sel


def _ensure_detail_selectors(html: str, url: str) -> DetailSelectors:
    sel = cache.get_detail_selectors(url)
    if sel is not None:
        return sel
    settings = get_settings()
    skeleton = to_skeleton(html, max_chars=settings.detail_skeleton_max_chars)
    sel = learn_detail_selectors(skeleton, url)
    cache.set_detail_selectors(url, sel)
    return sel


def _parse_list(html: str, base_url: str, sel: ListSelectors, max_items: int) -> list[NewsItem]:
    soup = BeautifulSoup(html, "lxml")
    container = soup.select_one(sel.container)
    if container is None:
        return []

    items: list[NewsItem] = []
    nodes = container.select(sel.item)
    for node in nodes:
        if len(items) >= max_items:
            break
        title_node = _select_one(node, sel.title) if sel.title else node
        url_node = _select_one(node, sel.url) if sel.url else None
        date_node = _select_one(node, sel.date) if sel.date else None

        title = _extract_attr(title_node, sel.title_attr)
        link = _extract_attr(url_node, sel.url_attr)
        if not title or not link:
            continue
        absolute = urljoin(base_url, link)
        date = _extract_attr(date_node, sel.date_attr) if sel.date else None
        items.append(NewsItem(title=title, url=absolute, date=date))
    return items


def _parse_detail(html: str, sel: DetailSelectors) -> NewsDetail:
    soup = BeautifulSoup(html, "lxml")
    title = _extract_attr(_select_one(soup, sel.title), "text") if sel.title else None
    date = _extract_attr(_select_one(soup, sel.date), "text") if sel.date else None
    source = _extract_attr(_select_one(soup, sel.source), "text") if sel.source else None

    content_node = _select_one(soup, sel.content)
    if content_node is not None:
        for bad in content_node.find_all(["script", "style"]):
            bad.decompose()
        paragraphs = [
            re.sub(r"\s+", " ", p.get_text(" ", strip=True)).strip()
            for p in content_node.find_all(["p", "div", "li"])
            if p.get_text(strip=True)
        ]
        if paragraphs:
            content = "\n".join(dict.fromkeys(p for p in paragraphs if p))
        else:
            content = re.sub(r"\s+", " ", content_node.get_text(" ", strip=True)).strip()
    else:
        content = ""
    return NewsDetail(title=title, date=date, source=source, content=content)


def extract_list_only(url: str, section: str, max_items: int = 20) -> list[NewsItem]:
    html = fetch_html(url)
    sel = _ensure_list_selectors(html, url, section)
    items = _parse_list(html, url, sel, max_items)
    if not items:
        # Selectors may be stale: relearn once.
        cache.clear(prefix=cache.list_key(url, section))
        sel = _ensure_list_selectors(html, url, section)
        items = _parse_list(html, url, sel, max_items)
    return items


def extract_detail(url: str) -> NewsDetail:
    html = fetch_html(url)
    sel = _ensure_detail_selectors(html, url)
    detail = _parse_detail(html, sel)
    if not detail.content:
        cache.clear(prefix=cache.detail_key(url))
        sel = _ensure_detail_selectors(html, url)
        detail = _parse_detail(html, sel)
    return detail


def extract_news(
    url: str,
    section: str,
    with_detail: bool = True,
    max_items: int = 20,
) -> list[NewsRecord]:
    items = extract_list_only(url, section, max_items=max_items)
    records: list[NewsRecord] = []
    for it in items:
        detail = extract_detail(it.url) if with_detail else None
        records.append(
            NewsRecord(title=it.title, url=it.url, date=it.date, detail=detail)
        )
    return records


def extract_with_rule(
    url: str,
    list_selectors: ListSelectors,
    detail_selectors: DetailSelectors | None = None,
    max_items: int = 5,
    with_detail: bool = True,
) -> list[NewsRecord]:
    """Pure extraction using pre-supplied selectors. No cache, no LLM, no writes.

    Applies date_patterns / date_output normalization on both list-page and
    detail-page dates so callers (refresh path) get ISO strings or None.
    """
    list_html = fetch_html(url)
    items = _parse_list(list_html, url, list_selectors, max_items)
    records: list[NewsRecord] = []
    for it in items:
        list_date_iso = normalize_pub_date(
            it.date, list_selectors.date_patterns, list_selectors.date_output
        )
        detail: NewsDetail | None = None
        if with_detail and detail_selectors is not None:
            detail_html = fetch_html(it.url)
            detail = _parse_detail(detail_html, detail_selectors)
            detail_date_iso = normalize_pub_date(
                detail.date, detail_selectors.date_patterns, detail_selectors.date_output
            )
            detail = detail.model_copy(update={"date": detail_date_iso})
        records.append(
            NewsRecord(title=it.title, url=it.url, date=list_date_iso, detail=detail)
        )
    return records
