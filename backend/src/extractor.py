"""High-level extraction: orchestrates cache lookup → LLM learning → DOM parsing.

Public API:
    extract_news(url, section, with_detail=True, max_items=20) -> list[NewsRecord]
    extract_list_only(url, section, max_items=20) -> list[NewsItem]
    extract_detail(url) -> NewsDetail
    extract_paginated(...) -> PaginatedResult  # 自动化抓取专用,带翻页 + 多种停止条件
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Literal
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
        if sel.url_regex:
            try:
                m = re.search(sel.url_regex, link)
            except re.error:
                m = None
            if m and m.groups():
                link = m.group(1)
            else:
                # regex 没命中 → 跳过本条,不要拿原始字面量去 urljoin 出错
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


# ===== 自动化抓取:翻页 + 多种停止条件 =====


StopReason = Literal[
    "quota",  # first_n / since_days 配额满
    "overlap",  # incremental 连续 K 条旧 url 即停;新 url 重置计数,容忍开头置顶
    "cutoff",  # since_days pub_date 早于 cutoff
    "max_pages",  # 翻页硬上限触发
    "max_items",  # 总条数硬上限触发
    "no_template",  # next_page_template 为 null,只能抓第 1 页
    "no_more_pages",  # 翻页拿到的 list 为空
    "fetch_error",  # 翻页 HTTP / 解析失败,优雅降级
]


@dataclass
class PaginatedResult:
    records: list[NewsRecord] = field(default_factory=list)
    pages_fetched: int = 0
    stop_reason: StopReason = "quota"


def _url_for_page(base_url: str, template: str, page: int, *, start: int = 2) -> str:
    """Resolve page-N URL: substitute {n} into template, then urljoin against base.

    `start` is the value of {n} that produces page 2's URL. Page N's index is
    `start + (page - 2)`. Default start=2 covers the common case where page 2
    is `index_2.html`; sites where page 2 is `index_1.html` (and `index_2.html`
    is actually page 3) pass start=1.

    Examples:
        base="https://x/col/123/index.html", template="index_{n}.html", page=2, start=2
            → ".../index_2.html"
        base="https://x/col/123/index.html", template="index_{n}.html", page=2, start=1
            → ".../index_1.html"
        base="https://x/list?page=1", template="?page={n}", page=2, start=2
            → ".../list?page=2"
    """
    if page < 2:
        raise ValueError("_url_for_page only resolves page>=2; page 1 is the base URL")
    idx = start + (page - 2)
    return urljoin(base_url, template.format(n=idx))


def _build_record(
    item: NewsItem,
    list_sel: ListSelectors,
    detail_sel: DetailSelectors | None,
    with_detail: bool,
) -> NewsRecord:
    list_date_iso = normalize_pub_date(item.date, list_sel.date_patterns, list_sel.date_output)
    detail: NewsDetail | None = None
    if with_detail and detail_sel is not None:
        try:
            detail_html = fetch_html(item.url)
            detail = _parse_detail(detail_html, detail_sel)
            detail_date_iso = normalize_pub_date(
                detail.date, detail_sel.date_patterns, detail_sel.date_output
            )
            detail = detail.model_copy(update={"date": detail_date_iso})
        except Exception:
            # 单条详情失败不应整批失败:留下 list 信息,detail=None
            detail = None
    return NewsRecord(title=item.title, url=item.url, date=list_date_iso, detail=detail)


def _effective_pub_date(rec: NewsRecord) -> str | None:
    """Final pub_date that would land in DB: list date 优先,fallback detail date."""
    if rec.date:
        return rec.date
    if rec.detail and rec.detail.date:
        return rec.detail.date
    return None


def extract_paginated(
    url: str,
    list_selectors: ListSelectors,
    detail_selectors: DetailSelectors | None,
    *,
    mode: Literal["first_n", "since_days", "incremental"],
    n: int | None = None,
    existing_urls: set[str] | None = None,
    max_pages: int = 5,
    max_items: int = 100,
    with_detail: bool = True,
    overlap_tolerance: int = 5,
) -> PaginatedResult:
    """自动化路径抓取:支持翻页 + 多种停止条件。

    mode:
      - 'first_n':       拿满 n 条停;n 必填。
      - 'since_days':    拿到 pub_date < (today-n) 停;n 必填(天数)。pub_date 缺失 → 收下不停。
      - 'incremental':   连续 overlap_tolerance 条 url 命中 existing_urls 即停;
                         新 url 重置计数,以容忍开头置顶帖。existing_urls 必填(可空集表示新订阅)。

    硬上限:max_pages 和 max_items 任一触发即停。next_page_template=None 只跑第 1 页。
    """
    if mode == "first_n" and (n is None or n < 1):
        raise ValueError("first_n mode requires n >= 1")
    if mode == "since_days" and (n is None or n < 1):
        raise ValueError("since_days mode requires n >= 1 (days)")
    if mode == "incremental" and existing_urls is None:
        raise ValueError("incremental mode requires existing_urls (may be empty set)")

    cutoff_iso: str | None = None
    if mode == "since_days" and n is not None:
        cutoff_dt = datetime.now(timezone.utc).date() - timedelta(days=n)
        cutoff_iso = cutoff_dt.strftime("%Y-%m-%d")  # compare lexicographically with ISO pub_date

    result = PaginatedResult()
    template = list_selectors.next_page_template
    start = list_selectors.next_page_start
    page = 1
    seen_in_run: set[str] = set()
    consecutive_old = 0  # incremental:连续命中 existing_urls 的计数,跨页累计;遇新 url 重置

    while True:
        if page > max_pages:
            result.stop_reason = "max_pages"
            return result
        if page == 1:
            page_url = url
        elif template:
            page_url = _url_for_page(url, template, page, start=start)
        else:
            result.stop_reason = "no_template"
            return result

        try:
            html = fetch_html(page_url)
            # 单页解析量取 max_items 上限,后续硬上限再裁;实际 _parse_list 的 max_items 仅是单页内的截断
            items = _parse_list(html, page_url, list_selectors, max_items=max_items)
        except Exception:
            if page == 1:
                # 第 1 页失败直接抛出,让上层记到 task.error
                raise
            result.stop_reason = "fetch_error"
            return result

        result.pages_fetched = page

        if not items:
            result.stop_reason = "no_more_pages" if page > 1 else "quota"
            return result

        for item in items:
            if item.url in seen_in_run:
                continue  # 防御:同一 run 内重复 url(站点列表自带重复)
            seen_in_run.add(item.url)

            if mode == "incremental" and item.url in (existing_urls or set()):
                # 连续命中 existing_urls 超过容忍阈值才停。
                # 这样既能跳过开头置顶(连续旧 url 数 ≤ 容忍阈值),
                # 又不会把「DB 因 first_n 配额没覆盖到的位置」误当作新内容回填。
                consecutive_old += 1
                if consecutive_old > overlap_tolerance:
                    result.stop_reason = "overlap"
                    return result
                continue

            consecutive_old = 0  # 新 url 重置;允许置顶 → 新内容 → 置顶 → 新内容 这种夹心结构
            rec = _build_record(item, list_selectors, detail_selectors, with_detail)
            pub = _effective_pub_date(rec)

            if mode == "since_days" and cutoff_iso is not None and pub is not None and pub < cutoff_iso:
                result.stop_reason = "cutoff"
                return result

            result.records.append(rec)

            if len(result.records) >= max_items:
                result.stop_reason = "max_items"
                return result
            if mode == "first_n" and n is not None and len(result.records) >= n:
                result.stop_reason = "quota"
                return result

        page += 1
        if not template:
            result.stop_reason = "no_template"
            return result
