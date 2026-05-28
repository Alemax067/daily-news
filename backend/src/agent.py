"""deepagents-based conversational agent that wraps the extractor tools."""

from __future__ import annotations

from typing import Any

from deepagents import create_deep_agent
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.base import BaseCheckpointSaver

from . import cache as cache_mod
from . import extractor
from .config import get_settings


_SYSTEM_PROMPT = """你是一个新闻抓取助手。用户会给你一个新闻列表页 URL 以及他们关心的板块名,\
你应当调用 `extract_news` 工具完成抓取并把结果整理成 Markdown 表格反馈给用户。

工作准则:
- 默认调用 `extract_news`(列表+详情一起返回)。
- 如果用户只要列表,改用 `extract_list_only`。
- 用户已经有列表 URL 想看其中某一条详情时,使用 `extract_detail`。
- 如果用户反馈"提取错了/为空/标题不对",调用 `clear_selector_cache` 清掉对应站点缓存,然后重试一次。
- 永远不要编造新闻条目,只展示工具返回的真实数据。
- 回答简洁:一段话简介 + 一张表格。详情字段过长时截断到 200 字并加省略号。

【新建订阅模式】
- 用户首次给你 URL + 板块名时,先用 `extract_news max_items=5` 抓取样例,展示表格等待用户反馈。
- 用户说"标题错了/对应不上/内容不对"等,调用 `clear_selector_cache(prefix=该URL的host)` 重试。
- 用户说"确认/可以了/保存/没问题",**告诉用户:点击界面上的『保存订阅』按钮**——你不要尝试自己保存。
"""


@tool
def extract_news(
    url: str,
    section: str,
    with_detail: bool = True,
    max_items: int = 20,
) -> dict[str, Any]:
    """抓取指定 URL 列表页内 `section` 板块的新闻条目;默认同时获取每条详情。

    Args:
        url: 新闻列表页完整 URL。
        section: 用户关注的板块名,例如 "上海要闻" / "北京要闻"。
        with_detail: 是否同时抓取每条新闻的详情正文,默认 True。
        max_items: 最多抓取多少条,默认 20。
    """
    records = extractor.extract_news(
        url=url, section=section, with_detail=with_detail, max_items=max_items
    )
    return {"count": len(records), "items": [r.model_dump() for r in records]}


@tool
def extract_list_only(url: str, section: str, max_items: int = 20) -> dict[str, Any]:
    """只抓取新闻列表(不进入详情页),适合用户只想看标题清单的场景。"""
    items = extractor.extract_list_only(url=url, section=section, max_items=max_items)
    return {"count": len(items), "items": [i.model_dump() for i in items]}


@tool
def extract_detail(url: str) -> dict[str, Any]:
    """抓取单个新闻详情页,返回 title/date/source/content。"""
    detail = extractor.extract_detail(url=url)
    return detail.model_dump()


@tool
def clear_selector_cache(prefix: str | None = None) -> dict[str, int]:
    """清除选择器缓存。prefix 可以是站点 host 或完整 cache key 子串;不传则全部清空。"""
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
        tools=[extract_news, extract_list_only, extract_detail, clear_selector_cache],
        system_prompt=_SYSTEM_PROMPT,
        checkpointer=checkpointer,
    )
