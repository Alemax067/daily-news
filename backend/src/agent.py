"""deepagents-based conversational agent for iterative selector debugging."""

from __future__ import annotations

from typing import Any, Literal

from bs4 import BeautifulSoup
from deepagents import create_deep_agent
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.base import BaseCheckpointSaver

from . import cache as cache_mod
from . import extractor
from .config import get_settings
from .fetcher import fetch_html
from .models import DetailSelectors, ListSelectors
from .skeleton import to_skeleton


_SYSTEM_PROMPT = """你是一个新闻抓取规则调试助手。目标:为用户给定的(列表页 URL + 板块名)\
迭代地生成一份能正确抓取的「列表选择器 JSON」和「详情选择器 JSON」,把日期解析模板固化下来,\
最后告诉用户点界面上的「保存订阅」。

可用工具:
- fetch_skeleton(url, max_chars=8000):抓 URL 并返回脱敏 HTML 骨架。骨架里大部分文本被替换成 _,\
  只有 h1-h6 保留原文,用来定位板块。
- try_list_selectors(url, selectors, max_items=5):用候选 list selectors 跑一遍,返回 \
  container_matched / item_count / samples(每条带 date_raw 和 date_normalized)。
- try_detail_selectors(url, selectors):用候选 detail selectors 跑一遍详情页,返回 \
  title / source / content_preview / content_length / date_raw / date_normalized。
- commit_selectors(target, url, selectors, section=None):把 target ∈ {"list","detail"} 的最终选择器落到\
  本次会话。**date 非 null 时,selectors 必须带 date_patterns: list[str] 和 date_output: \
  "iso_date"|"iso_datetime",否则会拒绝。**
- clear_selector_cache(prefix=None):推倒重来用,普通迭代不要轻易用。

工作流(必须按顺序):
1. fetch_skeleton(列表页 url) — 看骨架,定位板块。
2. 你自己输出 list_selectors JSON,调 try_list_selectors 验证。看 container_matched / item_count / samples。\
   不对就改 JSON 再 try;选择器太脆时可以再 fetch_skeleton 加大 max_chars 看更多结构。
3. samples 里有真实 date 字段时,**列表页日期优先**做 list date。看实际格式 → 决定 date_patterns 模板列表 \
   和 date_output。把它们写进 list_selectors,再 try 一次,确认 date_normalized 是 'YYYY-MM-DD' 或 \
   'YYYY-MM-DD HH:MM:SS' 就 OK。
4. 如果列表骨架里根本没有日期列,list_selectors.date 设为 null,date_patterns/date_output 都 null。
5. 从 samples 里挑一条真实文章 url,fetch_skeleton(详情 url),输出 detail_selectors JSON,\
   try_detail_selectors 验证 title / content。content_length 太短(<100)说明 content 选择器圈错了元素。
6. 详情页 date 处理:
   - 如果 list date 已经能拿到,**detail_selectors.date 设为 null,不重复抓**。
   - 如果列表无日期,detail.date 必填,且要在多个时间字段里挑「发布时间/发布日期/刊发时间/发表于」附近\
     的元素。**反例**:「更新时间/修改时间/责任编辑/浏览次数旁的时间戳/相关报道时间」都不是发布时间。\
     拿不准就多试几个候选选择器,对照 try_detail_selectors 返回的 date_raw 判断。给齐 date_patterns + date_output。
7. commit_selectors("list", 列表页 url, list_selectors, section=用户给的板块名)
8. commit_selectors("detail", 列表页 url, detail_selectors)  # detail 也传列表页 url 即可,内部按 host 建 key
9. 给用户展示一张 Markdown 表格(标题 / URL / 发布日期),告诉用户:点击界面上的「保存订阅」按钮 — \
   你不要自己保存。

日期模板硬规则:
- 看 samples 后**无法确定**日期格式时(如「05/06/2026」分不清月日序、纯相对时间「3 天前」、格式混合),\
  在对话里直接问用户,不要猜。
- 如果站点**只有相对时间**(「今天 14:30」「3 天前」)且没有任何绝对日期字段,告诉用户该站暂不支持入库,\
  请换一个 URL,**不要 commit_selectors**。

选择器规则:
- container 必须在页面里唯一;item 是 container 内相对选择器(常见 `li`、`dl`、`div.item`)。
- 短选择器优先,组合 class 而不是 :nth-child。
- title_attr:链接元素有 title="..." 时优先用 "title",否则 "text"。
- 详情 content 选 broadest article body 容器(如 `#mainText` / `.TRS_Editor` / `.article-content`)。
- 失败优先改选择器,不要轻易 clear_selector_cache。

ListSelectors JSON schema:
{
  "container": "...",  "item": "...",  "title": "...",
  "title_attr": "text" | "title",
  "url": "...",  "url_attr": "href",
  "date": "..." | null,  "date_attr": "text",
  "date_patterns": ["%Y-%m-%d", "%Y年%m月%d日", ...] | null,
  "date_output": "iso_date" | "iso_datetime" | null,
  "next_page_template": "index_{n}.html" | null
}

DetailSelectors JSON schema:
{
  "title": "..." | null,  "date": "..." | null,  "source": "..." | null,
  "content": "...",
  "date_patterns": [...] | null,
  "date_output": "iso_date" | "iso_datetime" | null
}
"""


@tool
def fetch_skeleton(url: str, max_chars: int = 8000) -> dict[str, Any]:
    """抓 URL 并返回脱敏 HTML 骨架。骨架里大部分文本节点被替换成 _,只有 h1-h6 保留原文,
    用于在生成选择器 JSON 前观察页面结构。

    Args:
        url: 要观察的页面 URL,列表页或详情页都可以。
        max_chars: 骨架最大字符数,过长做头尾截断。默认 8000。
    """
    html = fetch_html(url)
    skeleton = to_skeleton(html, max_chars=max_chars)
    return {
        "url": url,
        "skeleton": skeleton,
        "skeleton_length": len(skeleton),
        "html_length": len(html),
    }


def _list_samples_with_normalized(items: list, sel: ListSelectors) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for it in items:
        out.append(
            {
                "title": it.title,
                "url": it.url,
                "date_raw": it.date,
                "date_normalized": extractor.normalize_pub_date(
                    it.date, sel.date_patterns, sel.date_output
                ),
            }
        )
    return out


@tool
def try_list_selectors(
    url: str,
    selectors: dict[str, Any],
    max_items: int = 5,
) -> dict[str, Any]:
    """用候选 list selectors 对 URL 抓出来跑一遍,返回 container_matched / item_count / samples
    (每条带 date_raw 和 date_normalized)。用于在 commit 前迭代验证。

    Args:
        url: 列表页 URL。
        selectors: ListSelectors 的 JSON dict;date_patterns/date_output 可暂不填。
        max_items: 最多返回多少条样本。默认 5。
    """
    try:
        sel = ListSelectors.model_validate(selectors)
    except Exception as e:
        return {"error": f"ListSelectors 校验失败: {e}"}
    html = fetch_html(url)
    soup = BeautifulSoup(html, "lxml")
    try:
        container_matched = soup.select_one(sel.container) is not None
    except Exception as e:
        return {"error": f"container 选择器无效: {e}"}
    items = extractor._parse_list(html, url, sel, max_items)
    return {
        "container_matched": container_matched,
        "item_count": len(items),
        "samples": _list_samples_with_normalized(items, sel),
    }


@tool
def try_detail_selectors(
    url: str,
    selectors: dict[str, Any],
) -> dict[str, Any]:
    """用候选 detail selectors 抓详情页,返回 title / source / content_preview / 长度,
    并对 date 字段给 date_raw + date_normalized,便于在多个时间字段里挑发布时间。

    Args:
        url: 详情页 URL。
        selectors: DetailSelectors 的 JSON dict。
    """
    try:
        sel = DetailSelectors.model_validate(selectors)
    except Exception as e:
        return {"error": f"DetailSelectors 校验失败: {e}"}
    html = fetch_html(url)
    detail = extractor._parse_detail(html, sel)
    content = detail.content or ""
    return {
        "title": detail.title,
        "date_raw": detail.date,
        "date_normalized": extractor.normalize_pub_date(
            detail.date, sel.date_patterns, sel.date_output
        ),
        "source": detail.source,
        "content_length": len(content),
        "content_preview": content[:300] + ("…" if len(content) > 300 else ""),
    }


def _check_date_fields(sel_dict: dict[str, Any]) -> str | None:
    """date 非 null 时强制 date_patterns 和 date_output 必填且形态正确。"""
    if sel_dict.get("date") is None:
        return None
    patterns = sel_dict.get("date_patterns")
    if not isinstance(patterns, list) or not patterns or not all(isinstance(p, str) for p in patterns):
        return "date 非 null 时,date_patterns 必须是非空 strptime 模板列表(如 ['%Y-%m-%d', '%Y年%m月%d日'])"
    output = sel_dict.get("date_output")
    if output not in ("iso_date", "iso_datetime"):
        return 'date 非 null 时,date_output 必须是 "iso_date" 或 "iso_datetime"'
    return None


@tool
def commit_selectors(
    target: Literal["list", "detail"],
    url: str,
    selectors: dict[str, Any],
    section: str | None = None,
) -> dict[str, Any]:
    """把 target=「list」或「detail」的最终选择器落到本次会话。confirm 前必须 list 和 detail 各 commit 一次。

    date 非 null 时 selectors 必须带 date_patterns(list[str])和 date_output("iso_date"|"iso_datetime"),
    否则本工具会拒绝。

    Args:
        target: "list" 或 "detail"。
        url: 列表页 URL(detail commit 也传列表页 URL 即可;host 决定 cache key)。
        selectors: ListSelectors / DetailSelectors 的 JSON dict。
        section: list commit 时必传(用户给的板块名)。
    """
    err = _check_date_fields(selectors)
    if err is not None:
        return {"error": err}
    if target == "list":
        if not section:
            return {"error": "list commit 必须带 section(用户给的板块名)"}
        try:
            sel = ListSelectors.model_validate(selectors)
        except Exception as e:
            return {"error": f"ListSelectors 校验失败: {e}"}
        cache_mod.set_list_selectors(url, section, sel)
        return {"ok": True, "target": "list", "section": section}
    if target == "detail":
        try:
            sel = DetailSelectors.model_validate(selectors)
        except Exception as e:
            return {"error": f"DetailSelectors 校验失败: {e}"}
        cache_mod.set_detail_selectors(url, sel)
        return {"ok": True, "target": "detail"}
    return {"error": f"unknown target: {target!r}; 必须是 'list' 或 'detail'"}


@tool
def clear_selector_cache(prefix: str | None = None) -> dict[str, int]:
    """清除选择器缓存。prefix 可以是站点 host 或完整 cache key 子串;不传则全部清空。
    用于推倒重来。普通迭代请直接改 selectors 再 try,不要走这条。
    """
    n = cache_mod.clear(prefix=prefix)
    return {"cleared": n}


def build_chat_model() -> ChatOpenAI:
    s = get_settings()
    if not s.api_key:
        raise RuntimeError("DAILY_NEWS_AGENT_API_KEY is empty; set it in .env")
    return ChatOpenAI(
        model=s.model,
        api_key=s.api_key,
        base_url=s.base_url,
        temperature=s.temperature,
        max_completion_tokens=s.max_tokens,
        timeout=s.timeout,
        max_retries=s.max_retries,
        extra_body=s.extra_body or None,
    )


def build_agent(checkpointer: BaseCheckpointSaver | None = None):
    model = build_chat_model()
    return create_deep_agent(
        model=model,
        tools=[
            fetch_skeleton,
            try_list_selectors,
            try_detail_selectors,
            commit_selectors,
            clear_selector_cache,
        ],
        system_prompt=_SYSTEM_PROMPT,
        checkpointer=checkpointer,
    )
