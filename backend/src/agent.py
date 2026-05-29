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
- try_pagination(url, template, start=2, max_items=3):用 next_page_template + start 拼第 2 页 URL,\
  抓回来用已 commit 的 list selectors 跑样例,返回 next_page_url / item_count / samples。\
  在 list 已 commit 通过后再用,验证翻页规则可行。
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
4.5. **翻页规则探测(供自动化抓取使用)**:第 1 页就是用户给的 URL,**关键是把第 2 页定准**;\
   page 3+ 是简单的 index+1 推。两件事:**找模板** + **定 start**(第 2 页对应的 {n} 取值)。

   **第一步:找第 2 页的真实 href**。回看 list 页 fetch_skeleton 输出底部 `.changepage` / `.pagination` / \
   `#page` 容器,找页码链接 `<a>` 文本是 "2" 或"下一页"的那个,看它的 href。三类常见情况:
     a) 路径形 `index_1.html` / `index_2.html` / `index2.html` / `_2.shtml`
     b) query 形 `?page=1` / `?page=2` / `?pageNum=2`
     c) JS 渲染:容器内有 inline `<script>Pager({prefix:'index', suffix:'html', current:0, ...});\
        </script>`(current 是当前页号,通常 0 或 1)。骨架保留这种短脚本,**认真读 script body**。

   **第二步:推模板 + start**。把 href 里那个数字位换成 `{n}`,数字本身就是 start:
     - href=`index_1.html` → template=`index_{n}.html`, start=1(page 2 对应 n=1,index_2.html 是 page 3)
     - href=`index_2.html` → template=`index_{n}.html`, start=2(主流)
     - href=`index2.html`  → template=`index{n}.html`,  start=2
     - href=`?page=1`(且当前是 page 1 没 query)→ template=`?page={n}`, start=1
     - href=`?page=2` → template=`?page={n}`, start=2
     - JS Pager({current:0,...}) → start 通常 = current+2 或者直接看其它已渲染链接

   **第三步:验证**。先 commit_selectors("list", ...) 落库,再 try_pagination(url, template, start=…)。\
   **必须看 `looks_valid` 字段**;`looks_valid=false`(item_count=0 或 url 全部和第 1 页重合)就换 \
   start 或换模板再试。常见错配排查:start 写错时常见返回 item_count>0 但内容是 page 3,\
   骨架里的页码链接 href 是 ground truth,优先信它而不是猜。

   **fallback**:骨架里完全没有分页信息时,依次试 (template=`index_{n}.html`, start=2)、\
   (start=1)、(`?page={n}`, start=2)、(`?page={n}`, start=1) 几个候选;全部失败把 \
   next_page_template 设为 null 并重新 commit_selectors("list", ...)。\
   **该字段会被自动化抓取读取以做翻页;只在确认所有候选都不通时才 null,不要硬猜也不要偷懒**。
5. 从 samples 里挑一条真实文章 url,fetch_skeleton(详情 url),输出 detail_selectors JSON,\
   try_detail_selectors 验证 title / content。content_length 太短(<100)说明 content 选择器圈错了元素。
6. 详情页 date 处理:
   - 如果 list date 已经能拿到,**detail_selectors.date 设为 null,不重复抓**。
   - 如果列表无日期,detail.date 必填,且要在多个时间字段里挑「发布时间/发布日期/刊发时间/发表于」附近\
     的元素。**反例**:「更新时间/修改时间/责任编辑/浏览次数旁的时间戳/相关报道时间」都不是发布时间。\
     拿不准就多试几个候选选择器,对照 try_detail_selectors 返回的 date_raw 判断。给齐 date_patterns + date_output。
7. commit_selectors("list", 列表页 url, list_selectors, section=用户给的板块名)  # 翻页探测在这一步之后做也行
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
- **JS 跳转链接处理**:如果 a 标签的 href 是 `javascript:void(0)` 或 `#`,真实 URL 通常藏在 `onclick` 里\
  (常见模式:`onclick="jumpToDetail('./202605/t...html')"`、`onclick="openUrl('http://...')"`)。\
  这种情况下设 `url_attr: "onclick"` + 用 `url_regex` 抽真实路径,例如 `r"jumpToDetail\\('([^']+)'\\)"`、\
  `r"openUrl\\('([^']+)'\\)"`。骨架里的 onclick 属性是保留的,直接看就行。

ListSelectors JSON schema:
{
  "container": "...",  "item": "...",  "title": "...",
  "title_attr": "text" | "title",
  "url": "...",  "url_attr": "href" | "onclick" | "data-href" | "data-url",
  "url_regex": null | "正则,group(1) 是真实 URL",
  # 仅当 url_attr 取 onclick / data-* 且需要从其值里抠出 URL 时才填,\
  # 例如 r"jumpToDetail\\('([^']+)'\\)";正常 href 留 null
  "date": "..." | null,  "date_attr": "text",
  "date_patterns": ["%Y-%m-%d", "%Y年%m月%d日", ...] | null,
  "date_output": "iso_date" | "iso_datetime" | null,
  "next_page_template": "index_{n}.html" | "?page={n}" | null,
  # 该字段会被自动化抓取读取做翻页;无分页链接时设为 null,不要硬猜
  "next_page_start": 2
  # 第 2 页对应的 {n} 取值。多数站点 2(page2=index_2.html);少数 1(page2=index_1.html)。
  # 看页码链接 href 直接读出来。next_page_template 为 null 时本字段忽略,留默认 2 即可。
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


@tool
def try_pagination(
    url: str,
    section: str,
    template: str,
    start: int = 2,
    max_items: int = 3,
) -> dict[str, Any]:
    """用 next_page_template + start 拼出第 2 页 URL,抓回来用 cache 里已 commit 的 list selectors 跑样例。

    返回 next_page_url / item_count / overlap_with_page1 / looks_valid / samples。
    **必须先 commit_selectors("list", ...) 之后再调本工具**;{n} 会被替换为 `start`。
    判定:`looks_valid=true` 才算翻页可用;`item_count > 0` 但 `overlap_with_page1 == item_count`
    通常意味着站点忽略了未知参数(常见 `?page=2` 直接返回页 1 原样),换模板或换 start 再试。
    全部模板都不通才把 list_selectors.next_page_template 设为 null 重新 commit_selectors。

    Args:
        url: 列表页第 1 页 URL(就是用户给的那个)。
        section: 用户给的板块名,跟 commit_selectors("list", ..., section=...) 用的同一个。
        template: 翻页模板,如 "index_{n}.html"、"?page={n}"、"_{n}.html"。
        start: 第 2 页对应的 {n} 取值。多数站点是 2(page2=index_2.html);
            少数站点是 1(page2=index_1.html,index_2.html 其实是第 3 页)。
            page N 的 index = start + (N - 2)。默认 2。
        max_items: 最多返回多少条样本。默认 3。
    """
    if "{n}" not in template:
        return {"error": "template 必须包含 {n} 占位符,例如 'index_{n}.html'"}
    if start < 0:
        return {"error": "start 必须 >= 0"}
    sel = cache_mod.get_list_selectors(url, section)
    if sel is None:
        return {
            "error": "尚未 commit list_selectors;请先 commit_selectors('list', url, ..., section=...) 再调本工具"
        }
    try:
        next_url = extractor._url_for_page(url, template, 2, start=start)
    except Exception as e:
        return {"error": f"模板拼接失败: {e}"}
    try:
        html = fetch_html(next_url)
    except Exception as e:
        return {"next_page_url": next_url, "error": f"抓取第 2 页失败: {e}"}
    items = extractor._parse_list(html, next_url, sel, max_items)
    # 防误报:有的站点对未知 query 直接忽略,?page=2 返回页 1 原样。
    # 抓一次第 1 页对比 url 集合,若全重合说明模板无效。
    try:
        page1_html = fetch_html(url)
        page1_items = extractor._parse_list(page1_html, url, sel, max_items=20)
        page1_urls = {it.url for it in page1_items}
    except Exception:
        page1_urls = set()
    item_urls = {it.url for it in items}
    overlap_with_page1 = len(item_urls & page1_urls)
    looks_valid = len(items) > 0 and overlap_with_page1 < len(items)
    return {
        "next_page_url": next_url,
        "start_used": start,
        "item_count": len(items),
        "overlap_with_page1": overlap_with_page1,
        "looks_valid": looks_valid,
        "samples": [
            {"title": it.title, "url": it.url, "date_raw": it.date}
            for it in items
        ],
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
            try_pagination,
            commit_selectors,
            clear_selector_cache,
        ],
        system_prompt=_SYSTEM_PROMPT,
        checkpointer=checkpointer,
    )
