"""deepagents-based conversational agent for iterative selector debugging."""

from __future__ import annotations

from typing import Any, Literal
from urllib.parse import urlparse

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

**硬约束:用户给的列表页 URL 是固定的,不允许换。** try_list_selectors / try_pagination / \
commit_selectors 都必须用用户原始的那个 URL。即使页面是 redirect / 空壳 / JS 渲染抓不到内容,\
也不要去试别的 URL——这种情况直接告诉用户「该站点暂不支持,请换一个 URL」,**不要 commit**。\
fetch_skeleton / fetch_text / try_detail_selectors 抓详情页样本或外链 JS 是允许的(URL 必须从骨架/源码里来)。

**列表抓取有两种模式**:`css`(传统 HTML + CSS 选择器)、`json`(站点用 JS 模板渲染,数据走后端 JSON API)。\
**先用 fetch_skeleton 判定模式,然后只走一条工作流,字段不要混填**。详情页一律走 CSS。

可用工具:
- fetch_skeleton(url, max_chars=8000):抓 URL 并返回脱敏 HTML 骨架。骨架里大部分文本被替换成 _,\
  只有 h1-h6 保留原文,用来定位板块。**外链 `<script src="..."/>` 的路径会保留**(JSON 模式定位 API 关键)。
- fetch_text(url, max_chars=8000):抓 URL 返回原文,不做骨架化。**专用于读外链 JS 源码**找 ajax 配置;\
  详情页探查请用 fetch_skeleton 而不是 fetch_text。
- try_list_selectors(url, selectors, max_items=5):用候选 list selectors 跑一遍,返回 \
  `container_matched`(CSS 模式)或 `endpoint_reachable`(JSON 模式)/ `item_count` / `samples`\
  (每条带 date_raw 和 date_normalized)。
- try_detail_selectors(url, selectors):用候选 detail selectors 跑一遍详情页,返回 \
  title / source / content_preview / content_length / date_raw / date_normalized。
- try_pagination(url, section, template, start=2, max_items=3):验证翻页规则。\
  CSS 模式:用 next_page_template + start 拼第 2 页 URL。\
  JSON 模式:**template/start 参数被工具忽略**(传 `template=""`,`start=0` 即可),工具自己读 \
  `json_page_param`+`json_page_start` 拼第 2 页 body。\
  必须先 commit_selectors("list", ...) 之后再用。
- commit_selectors(target, url, selectors, section=None):把 target ∈ {"list","detail"} 的最终选择器落到\
  本次会话。**date 非 null 时,selectors 必须带 date_patterns: list[str] 和 date_output: \
  "iso_date"|"iso_datetime",否则会拒绝。**
- clear_selector_cache(prefix=None):推倒重来用,普通迭代不要轻易用。

═══════ 模式判定(第一步必做)═══════

`fetch_skeleton(列表页 url, max_chars=8000)` → 在骨架里找以下信号,**任一命中即 JSON 模式**:
1. **模板字面量**(最明确信号):
   - doT.js:`{{= item.url }}` / `{{~ data :item }}` / `{{? cond }}` / `{{! ... }}`
   - ASP-style:`<%= varname %>` / `<%- varname %>` / `<% if(...) %>`
   - Vue mustache:`{{ varname }}` 在 li / div / span 等结构标签内
2. **空壳容器**:列表预期容器(常见 `<ul id="list">` / `<ul class="news-list">` / `<div id="newsList">`)\
   下面**没有任何 li/dd 子元素**(骨架里只有 `<ul .../>` 自闭),同时页面里有 \
   `list_*.js` / `news_*.js` / `data_*.js` / `search_*.js` 这种外链 script。
3. **明显的搜索/查询 JS API 入口**:骨架顶部出现 `<script src="...api...">` / `<script src="...search...">`,\
   且列表区域是空容器。

**全部信号都没有 → CSS 模式**。判定结果写出来再继续(口头说一句即可,不必落到工具调用)。

═══════ CSS 工作流 ═══════

1. fetch_skeleton 你已经做了,看骨架定位板块容器。
2. 输出 list_selectors JSON(`mode: "css"` + container/item/title/url 四件套),调 \
   try_list_selectors 验证。看 `container_matched` / `item_count` / `samples`。\
   不对就改 JSON 再 try;选择器太脆时可以再 fetch_skeleton 加大 max_chars 看更多结构。
3. samples 里有真实 date 字段时,**列表页日期优先**做 list date。看实际格式 → 决定 date_patterns 模板列表 \
   和 date_output。把它们写进 list_selectors,再 try 一次,确认 date_normalized 是 'YYYY-MM-DD' 或 \
   'YYYY-MM-DD HH:MM:SS' 就 OK。
4. 如果列表骨架里根本没有日期列,list_selectors.date 设为 null,date_patterns/date_output 都 null。
4.5. **翻页规则探测(供自动化抓取使用)**:第 1 页就是用户给的 URL,**关键是把第 2 页定准**;\
   page 3+ 是简单的 index+1 推。两件事:**找模板** + **定 start**(第 2 页对应的 {n} 取值)。

   **第一步:找第 2 页的真实 href(强制)**。回看 list 页 fetch_skeleton 输出底部的 \
   `.changepage` / `.pagination` / `#page` / `.page` / `.pageBox` / `.pagelist` 容器,\
   找文本是 "2" / "下一页" / "next" 的那个 `<a>`,看它的 href。\
   **如果当前骨架里看不到分页区**(默认 max_chars=8000 经常截掉页底),\
   **必须**先 `fetch_skeleton(url, max_chars=20000)` 甚至 30000 重新抓一次,直到能看到分页区/分页 script,\
   再继续。**不要直接套默认 start=2,这是错误的偷懒方式**——很多政府站(如 beijing.gov.cn 部分栏目)\
   page 2 就是 `index_1.html`,不是 `index_2.html`。三类常见情况:
     a) 路径形 `index_1.html` / `index_2.html` / `index2.html` / `_2.shtml`
     b) query 形 `?page=1` / `?page=2` / `?pageNum=2`
     c) JS 渲染:容器内有 inline `<script>createPageHTML(...)` / `<script>Pager({prefix:'index', \
        suffix:'html', current:0, ...});</script>`(current 是当前页号,通常 0 或 1)。\
        骨架保留这种短脚本,**认真读 script body**。

   **第二步:推模板 + start**。把 href 里那个数字位换成 `{n}`,数字本身就是 start:
     - href=`index_1.html` → template=`index_{n}.html`, start=1(page 2 对应 n=1,index_2.html 是 page 3)
     - href=`index_2.html` → template=`index_{n}.html`, start=2(主流)
     - href=`index2.html`  → template=`index{n}.html`,  start=2
     - href=`?page=1`(且当前是 page 1 没 query)→ template=`?page={n}`, start=1
     - href=`?page=2` → template=`?page={n}`, start=2
     - JS Pager({current:0,...}) → start 通常 = current+2 或者直接看其它已渲染链接

   **第三步:验证**。先 commit_selectors("list", ...) 落库,再 \
   try_pagination(url, section, template, start=…)。**必看两个字段**:
     - `looks_valid` 必须是 `true`
     - `offset_warning` 必须是 `null`
   `offset_warning` 非空表示工具检测到当前 start 错了(start-1 也返回了不同的有效条目,\
   说明你拿到的其实是第 3 页),警告文本会指出正确的 start——**按它说的重新 try_pagination**。

   **fallback**:骨架翻到 30000 字符还看不到分页(站点全靠 JS 异步加载),\
   依次试 (template=`index_{n}.html`, start=1)、(`index_{n}.html`, start=2)、\
   (`?page={n}`, start=1)、(`?page={n}`, start=2);**优先试 start=1 这一组**——offset 站点用 start=2 试会假阳性,\
   而 start=1 在主流站点上 try_pagination 会触发 offset 检测/或直接返回 page 1 副本。\
   全部失败把 next_page_template 设为 null 并重新 commit_selectors("list", ...)。\
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

═══════ JSON 工作流 ═══════

1. fetch_skeleton 已经做了。从骨架里挖三类信息记下来:
   a) **目标列表容器的 id/class**(如 `<ul id="list"/>` 或 `<div id="newsList"/>`),后面对应的 ajax 渲染目标。
   b) **inline 短脚本里的关键变量**,常见 `var channelId='100782'` / `var siteId=...` / \
      `var keyword='xxx'`。这些是 endpoint 路径或 body 字段的真值来源。
   c) **外链 JS 列表**:骨架里 `<script src="..."/>` 的路径。**优先级**:`list*.js` > `news*.js` > \
      `data*.js` > `search*.js` > 其它业务 JS。jQuery / 框架库(`jquery*.js` / `vue*.js` / `bootstrap*.js`)直接跳过。

2. 把候选 JS 路径(相对路径用列表页 url 转绝对)逐个 fetch_text 抓源码,在源码里找 ajax 调用:
   - 主流:`$.ajax({type:'POST', url:..., data:..., dataType:'json', success:fn})`
   - 也常见:`fetch(url, {method:'POST', body:...})`、`axios.post(url, body)`、`$.post/get(...)`
   抠出三件套:
   - **endpoint**:url 字段。`location.protocol+'//api.xxx.gov.cn/path/'+channelId` 这种拼接式,\
     **手动把变量替换为真值**(channelId 取自第 1 步的 inline 变量)。结果如 \
     `https://api.hunan.gov.cn/search/common/search/100782`。
   - **method**:`type/method` 字段,GET 或 POST。
   - **body 字段**:`data: {...}` 整体。jQuery 嵌套写法 `data:{datas:[{key:'status',value:1}]}` \
     在网络请求里会被序列化成 `datas[0][key]=status&datas[0][value]=1`,你**直接展平到 dict**:\
     `{"datas[0][key]": "status", "datas[0][value]": "1"}`。**这是规范**,工具按 form-encoded 发出去。
   源码看不懂或拿不到就换下一个 JS 候选;最多试 3 个,都不通告诉用户该站点暂不支持。

3. 输出 mode='json' 的 ListSelectors。**关键字段映射**靠 try_list_selectors 之后看 results[0] 的真实 key:
   - `json_endpoint`:第 2 步抠出来的完整 URL(变量替换后)
   - `json_method` / `json_body`:同上
   - `json_results_path`:点路径定位 results 数组,常见 `"data.results"` / `"result.list"` / `"data"`
   - `json_url_field` / `json_title_field` / `json_date_field`:results[0] 里对应字段名,如 \
     `"url"` / `"title"` / `"publishedTimeStr"`。**不确定时先 try 一次,看 samples 里 raw key 反推**。

4. try_list_selectors(url, selectors, max_items=5):看 `endpoint_reachable=true`,\
   `item_count` 合理(>0),samples 里 url(绝对地址)/title/date_raw 形态对。\
   **失败排查**:
   - endpoint_reachable=false → endpoint 错了或 referer 校验严,看 error 提示;\
     有些 API 必须从 fetch_text 抓到的源码里看是否有自定义请求头要求(目前工具没法加自定义头,\
     这种站点暂不支持,告诉用户)。
   - endpoint_reachable=true,item_count=0 → results_path 不对,在 samples 看不到时直接\
     在 try_list_selectors 之外加一次最小化的 fetch_text(json_endpoint) 看返回结构(API 多数支持 GET \
     测试),然后修 results_path / 字段名。
   - samples 里 url 是相对路径(如 `/info/123`)→ urljoin 已经按 base_url(列表页 URL)拼了,\
     如果实际需要拼到 API host 而不是站点 host,设 `json_url_prefix` 为 API host。
   填好 date_patterns / date_output 后再 try 一次,确认 date_normalized 形态对。

5. **翻页字段**:回到 fetch_text 抓的 JS 源码,看 ajax body 里的翻页字段:
   - 常见:`page` / `pageNum` / `_page` / `pageIndex` / `pageNo` / `start`(start 一般是偏移量,语义不同)
   - body 里有 `pageSize:10` / `rows:20` 这种,**保留在 json_body 默认值里**,不动。
   设 `json_page_param` 为翻页字段名;`json_page_start` 看实际语义:
   - body 默认值 `page:1` 且语义是「第几页」→ json_page_start=1(主流)
   - body 默认值 `page:0` 且 0 表示首页 → json_page_start=0
   - 偏移量语义(`start:0` 表示从第 0 条开始)→ 不属于本工具支持的简单翻页,设 json_page_param=null

   commit_selectors("list", ..., section=...) 之后调 \
   `try_pagination(url, section, template="", start=0, max_items=3)`:\
   工具会读 sel.mode='json' → **忽略 template/start**,自己拼 page 2 body 验证。\
   看 `looks_valid=true`、`overlap_with_page1=0`(或很小)即翻页可用。\
   API 没翻页字段时(整页一次返回),json_page_param=null,**直接跳过 try_pagination**(commit 一次即可)。

6. **详情页一律走 CSS**(v1 不支持 JSON detail,即使 list API 自带 content 字段也不要尝试合并)。\
   从 samples 挑一条详情 url → fetch_skeleton(详情 url) → 输出 DetailSelectors → try_detail_selectors。\
   规则与 CSS 工作流第 5-6 步完全一样(content broadest 容器、date 字段挑发布时间不挑更新时间等)。

7. commit_selectors("detail", 列表页 url, detail_selectors)。

8. 给用户 Markdown 表格(标题 / URL / 发布日期)+ 提示「点击保存订阅」。

JSON 模式踩坑速记:
- **detail 别 JSON**:list API 即使返回 content 字段,v1 仍单独抓详情页;不要把 detail_selectors 也搞 JSON。
- **变量真值**:channelId 等先看列表页 inline `<script>` 的 var 声明,然后看 url path 里某段数字,\
  最后看 JS 源码默认值。优先级从高到低。
- **referer**:工具会自动用列表页 URL 当 referer,跨域 API(`api.xxx.gov.cn` ↔ `www.xxx.gov.cn`)通常没问题。
- **绝对地址**:json_endpoint 写完整 URL 最安全;实在要用相对路径,工具会用列表页 URL urljoin。

═══════ 共用规则 ═══════

日期模板硬规则:
- 看 samples 后**无法确定**日期格式时(如「05/06/2026」分不清月日序、纯相对时间「3 天前」、格式混合),\
  在对话里直接问用户,不要猜。
- 如果站点**只有相对时间**(「今天 14:30」「3 天前」)且没有任何绝对日期字段,告诉用户该站暂不支持入库,\
  请换一个 URL,**不要 commit_selectors**。

CSS 选择器规则:
- container 必须在页面里唯一;item 是 container 内相对选择器(常见 `li`、`dl`、`div.item`)。
- 短选择器优先,组合 class 而不是 :nth-child。
- title_attr:链接元素有 title="..." 时优先用 "title",否则 "text"。
- 详情 content 选 broadest article body 容器(如 `#mainText` / `.TRS_Editor` / `.article-content`)。
- 失败优先改选择器,不要轻易 clear_selector_cache。
- **JS 跳转链接处理**:如果 a 标签的 href 是 `javascript:void(0)` 或 `#`,真实 URL 通常藏在 `onclick` 里\
  (常见模式:`onclick="jumpToDetail('./202605/t...html')"`、`onclick="openUrl('http://...')"`)。\
  这种情况下设 `url_attr: "onclick"` + 用 `url_regex` 抽真实路径,例如 `r"jumpToDetail\\('([^']+)'\\)"`、\
  `r"openUrl\\('([^']+)'\\)"`。骨架里的 onclick 属性是保留的,直接看就行。

ListSelectors JSON schema(两种模式并列;**只填当前模式那组,另一组留默认/null**):
{
  "mode": "css" | "json",  // **必填**

  // ====== 仅 mode='css' 用 ======
  "container": "...",  "item": "...",  "title": "...",
  "title_attr": "text" | "title",
  "url": "...",  "url_attr": "href" | "onclick" | "data-href" | "data-url",
  "url_regex": null | "正则,group(1) 是真实 URL",
  "date": "..." | null,  "date_attr": "text",
  "next_page_template": "index_{n}.html" | "?page={n}" | null,
  "next_page_start": 2,

  // ====== 仅 mode='json' 用 ======
  "json_endpoint": "https://api.xxx.gov.cn/...",  // 完整 URL(变量替换后);相对路径会按列表页 url urljoin
  "json_method": "POST" | "GET",
  "json_body": {"channelId": "100782", "page": "1"} | null,  // form-encoded(POST)或 query(GET)
  "json_results_path": "data.results",  // 点路径定位 results 数组
  "json_url_field": "url",
  "json_url_prefix": "",  // 拼到 results[i][url_field] 前的固定前缀,通常空
  "json_title_field": "title",
  "json_date_field": "publishedTimeStr" | null,
  "json_page_param": "page" | "pageNum" | null,  // null 表示该 API 无翻页
  "json_page_start": 1,

  // ====== 两种模式共用(date 取出来后归一化) ======
  "date_patterns": ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d", ...] | null,
  "date_output": "iso_date" | "iso_datetime" | null
}

DetailSelectors JSON schema(始终走 CSS):
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
    try:
        html = fetch_html(url)
    except Exception as e:
        return {"url": url, "error": f"抓取失败: {e}"}
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

    **url 必须与用户给的列表页 URL 一致,不允许换。**如果用户的 URL 抓不到内容(redirect / JS \
    渲染 / 反爬),告诉用户该站点暂不支持,不要去试其他 URL。

    Args:
        url: 列表页 URL,必须与用户在创建订阅时给的一致。
        selectors: ListSelectors 的 JSON dict;date_patterns/date_output 可暂不填。
        max_items: 最多返回多少条样本。默认 5。
    """
    sess = cache_mod.session_target()
    if sess is not None:
        sess_url, _ = sess
        if url != sess_url:
            return {
                "error": (
                    f"url 必须用用户给的列表页 URL,不允许换。"
                    f"会话目标:{sess_url!r};你传入的:{url!r}。"
                    f"如果用户的 URL 抓不到内容(redirect / JS 渲染 / 反爬),"
                    f"告诉用户该站点暂不支持,不要换 url。"
                )
            }
    try:
        sel = ListSelectors.model_validate(selectors)
    except Exception as e:
        return {"error": f"ListSelectors 校验失败: {e}"}

    # JSON 模式:不抓 HTML,直接打 API
    if sel.mode == "json":
        try:
            items = extractor._parse_list_json(url, sel, max_items)
        except Exception as e:
            return {
                "endpoint_reachable": False,
                "error": f"JSON API 调用 / 解析失败: {e}",
            }
        return {
            "endpoint_reachable": True,
            "item_count": len(items),
            "samples": _list_samples_with_normalized(items, sel),
        }

    # CSS 模式
    try:
        html = fetch_html(url)
    except Exception as e:
        return {"url": url, "error": f"抓取失败: {e}"}
    soup = BeautifulSoup(html, "lxml")
    try:
        container_matched = soup.select_one(sel.container) is not None
    except Exception as e:
        return {"error": f"container 选择器无效: {e}"}
    try:
        items = extractor._parse_list_css(html, url, sel, max_items)
    except Exception as e:
        return {"error": f"item / 内层选择器无效或解析失败: {e}"}
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
    try:
        html = fetch_html(url)
    except Exception as e:
        return {"url": url, "error": f"抓取失败: {e}"}
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

    返回 next_page_url / item_count / overlap_with_page1 / looks_valid / offset_warning / samples。
    **必须先 commit_selectors("list", ...) 之后再调本工具**;{n} 会被替换为 `start`。

    判定:
    - `looks_valid=true` 且 `offset_warning=null` 才算翻页可用。
    - `looks_valid=false` + `overlap_with_page1 == item_count`:站点忽略未知参数,模板/start 都得换。
    - `offset_warning != null`:站点是 offset 站(真正 start 比当前小 1)。
      警告文本会告诉你正确的 start 值,**直接按提示重新调一次本工具验证**,不要无视。
    全部模板 × start 组合都不通才把 list_selectors.next_page_template 设为 null 重新 commit_selectors。

    **JSON 模式下**(已 commit 的 list_selectors.mode='json'):template / start 这两个参数会被忽略,
    工具直接读 list_selectors.json_page_param + json_page_start 自己拼第 2 页 body 去验证;
    template 传 "" 即可。json_page_param=null 时本工具直接报错(意味着 API 没翻页字段)。

    Args:
        url: 列表页第 1 页 URL(就是用户给的那个)。
        section: 用户给的板块名,跟 commit_selectors("list", ..., section=...) 用的同一个。
        template: 翻页模板,如 "index_{n}.html"、"?page={n}"、"_{n}.html"。JSON 模式下传 ""。
        start: 第 2 页对应的 {n} 取值。多数站点是 2(page2=index_2.html);
            少数站点是 1(page2=index_1.html,index_2.html 其实是第 3 页)。
            page N 的 index = start + (N - 2)。默认 2。JSON 模式下忽略。
        max_items: 最多返回多少条样本。默认 3。
    """
    sess = cache_mod.session_target()
    if sess is not None:
        sess_url, sess_section = sess
        if cache_mod.list_key(url, section) != cache_mod.list_key(sess_url, sess_section or ""):
            return {
                "error": (
                    f"url/section 必须与会话目标一致,不允许换。"
                    f"会话目标:url={sess_url!r}, section={sess_section!r};"
                    f"你传入的:url={url!r}, section={section!r}。"
                )
            }
    sel = cache_mod.get_list_selectors(url, section)
    if sel is None:
        return {
            "error": "尚未 commit list_selectors;请先 commit_selectors('list', url, ..., section=...) 再调本工具"
        }

    # ===== JSON 模式:忽略 template/start,用 json_page_param 拼 page=2 =====
    if sel.mode == "json":
        if not sel.json_page_param:
            return {
                "error": (
                    "list_selectors.json_page_param 为 null,该 API 没有翻页字段。"
                    "如果确实没翻页,告诉用户翻页不可用即可,不要继续调本工具。"
                )
            }
        try:
            items = extractor._parse_list_json(url, sel, max_items, page=2)
        except Exception as e:
            return {"error": f"JSON API page 2 调用失败: {e}"}
        try:
            page1_items = extractor._parse_list_json(url, sel, max_items=20, page=1)
            page1_urls = {it.url for it in page1_items}
        except Exception:
            page1_urls = set()
        item_urls = {it.url for it in items}
        overlap_with_page1 = len(item_urls & page1_urls)
        looks_valid = len(items) > 0 and overlap_with_page1 < len(items)
        return {
            "next_page_url": None,
            "page_param": sel.json_page_param,
            "page_param_value": str(sel.json_page_start + 1),
            "item_count": len(items),
            "overlap_with_page1": overlap_with_page1,
            "looks_valid": looks_valid,
            "offset_warning": None,
            "samples": [
                {"title": it.title, "url": it.url, "date_raw": it.date}
                for it in items
            ],
        }

    # ===== CSS 模式 =====
    if "{n}" not in template:
        return {"error": "template 必须包含 {n} 占位符,例如 'index_{n}.html'"}
    if start < 0:
        return {"error": "start 必须 >= 0"}
    try:
        next_url = extractor._url_for_page(url, template, 2, start=start)
    except Exception as e:
        return {"error": f"模板拼接失败: {e}"}
    try:
        html = fetch_html(next_url)
    except Exception as e:
        return {"next_page_url": next_url, "error": f"抓取第 2 页失败: {e}"}
    try:
        items = extractor._parse_list_css(html, next_url, sel, max_items)
    except Exception as e:
        return {
            "next_page_url": next_url,
            "error": f"已 commit 的 list 选择器在第 2 页解析失败: {e}",
        }
    # 防误报:有的站点对未知 query 直接忽略,?page=2 返回页 1 原样。
    # 抓一次第 1 页对比 url 集合,若全重合说明模板无效。
    try:
        page1_html = fetch_html(url)
        page1_items = extractor._parse_list_css(page1_html, url, sel, max_items=20)
        page1_urls = {it.url for it in page1_items}
    except Exception:
        page1_urls = set()
    item_urls = {it.url for it in items}
    overlap_with_page1 = len(item_urls & page1_urls)
    looks_valid = len(items) > 0 and overlap_with_page1 < len(items)

    # Offset 检测:start>=2 时也试一下 start-1。
    # 例如 Beijing /ywdt/yaowen/:真实 start=1,page2=index_1.html,page3=index_2.html。
    # 用 start=2 调 → 拿到 index_2.html(其实是 page 3),overlap_with_page1=0 也 looks_valid=true,假阳性。
    # 此时 start-1 (即 index_1.html) 也会返回有效条目,且与 page 1 + 与 start 候选都不重合 →
    # 这个签名意味着站点是 offset 站(真 start = start - 1)。
    offset_warning: str | None = None
    if looks_valid and start >= 1:
        try:
            prev_url = extractor._url_for_page(url, template, 2, start=start - 1)
        except Exception:
            prev_url = None
        if prev_url and prev_url != next_url and prev_url != url:
            try:
                prev_html = fetch_html(prev_url)
                prev_items = extractor._parse_list_css(prev_html, prev_url, sel, max_items)
                prev_urls = {it.url for it in prev_items}
            except Exception:
                prev_urls = set()
            # start-1 返回有效条目,且既不与 page 1 重合,也不与 start 候选重合 → offset 站点
            if (
                prev_urls
                and prev_urls.isdisjoint(page1_urls)
                and prev_urls.isdisjoint(item_urls)
            ):
                looks_valid = False
                offset_warning = (
                    f"start={start - 1} 也返回了有效条目,且与第 1 页、与 start={start} 都不重合。"
                    f"这说明站点真正的 start 是 {start - 1}(page 2 = {prev_url}),"
                    f"当前 start={start} 实际抓到的是第 3 页内容。"
                    f"用 start={start - 1} 重新调 try_pagination 验证后再 commit_selectors。"
                )
    return {
        "next_page_url": next_url,
        "start_used": start,
        "item_count": len(items),
        "overlap_with_page1": overlap_with_page1,
        "looks_valid": looks_valid,
        "offset_warning": offset_warning,
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

    **url / section 必须与用户在创建订阅时给的一致**——本工具会按会话目标校验,不允许偷换 url
    或板块名(否则 cache key 与保存时的查找 key 对不上,会保存失败)。如果用户给的 url 抓不到内容,
    在对话里告诉用户该站点暂不支持,**不要 commit**;只有翻页规则不可用时,才把 list_selectors.
    next_page_template 设为 null 重新 commit,这是允许的 fallback。

    Args:
        target: "list" 或 "detail"。
        url: 列表页 URL(detail commit 也传列表页 URL 即可;host 决定 cache key)。
        selectors: ListSelectors / DetailSelectors 的 JSON dict。
        section: list commit 时必传(用户给的板块名)。
    """
    err = _check_date_fields(selectors)
    if err is not None:
        return {"error": err}
    sess = cache_mod.session_target()
    if target == "list":
        if not section:
            return {"error": "list commit 必须带 section(用户给的板块名)"}
        try:
            sel = ListSelectors.model_validate(selectors)
        except Exception as e:
            return {"error": f"ListSelectors 校验失败: {e}"}
        if sess is not None:
            sess_url, sess_section = sess
            if cache_mod.list_key(url, section) != cache_mod.list_key(sess_url, sess_section or ""):
                return {
                    "error": (
                        f"提交的 url/section 与本会话目标不一致。"
                        f"会话目标:url={sess_url!r}, section={sess_section!r};"
                        f"你提交的:url={url!r}, section={section!r}。"
                        f"必须按用户给的目标提交;若用户的 url 抓不到内容,"
                        f"告诉用户该站点暂不支持,不要换 url。"
                        f"翻页失败请把 next_page_template 设为 null 重新 commit。"
                    )
                }
        cache_mod.set_list_selectors(url, section, sel)
        return {"ok": True, "target": "list", "section": section}
    else:  # target == "detail"
        try:
            sel = DetailSelectors.model_validate(selectors)
        except Exception as e:
            return {"error": f"DetailSelectors 校验失败: {e}"}
        if sess is not None:
            sess_url, _ = sess
            if urlparse(url).netloc != urlparse(sess_url).netloc:
                return {
                    "error": (
                        f"detail commit 的 url host ({urlparse(url).netloc!r}) 与会话目标 host "
                        f"({urlparse(sess_url).netloc!r}) 不一致;必须用同站点 url。"
                    )
                }
        cache_mod.set_detail_selectors(url, sel)
        return {"ok": True, "target": "detail"}


@tool
def clear_selector_cache(prefix: str | None = None) -> dict[str, int]:
    """清除选择器缓存。prefix 可以是站点 host 或完整 cache key 子串;不传则全部清空。
    用于推倒重来。普通迭代请直接改 selectors 再 try,不要走这条。
    """
    n = cache_mod.clear(prefix=prefix)
    return {"cleared": n}


@tool
def fetch_text(url: str, max_chars: int = 8000) -> dict[str, Any]:
    """抓 URL 返回原文(不做 HTML 骨架化),专门用来读外链 JS / 文本资源,定位 JSON API 端点。

    JSON 模式工作流里:fetch_skeleton 看到列表容器是空壳 + 模板字面量(`{{=}}` / `<%=%>` / Vue mustache),
    在骨架底部找到 `<script src="..."/>` 路径,**把那个路径用 fetch_text 抓回来**,在源码里找
    `$.ajax({url, data, type})` / `fetch(...)` / `axios.{get|post}(...)`,抠出 endpoint / method /
    body 字段名 / channelId 等变量真值。

    Args:
        url: 要抓的 URL,通常是骨架里看到的 <script src="..."> 路径(相对路径请先转成绝对地址)。
        max_chars: 截断上限。默认 8000;源码很长就调到 20000 再 fetch 一次。
    """
    try:
        text = fetch_html(url)
    except Exception as e:
        return {"url": url, "error": f"抓取失败: {e}"}
    return {
        "url": url,
        "text": text[:max_chars],
        "text_length": len(text),
        "truncated": len(text) > max_chars,
    }


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
            fetch_text,
            try_list_selectors,
            try_detail_selectors,
            try_pagination,
            commit_selectors,
            clear_selector_cache,
        ],
        system_prompt=_SYSTEM_PROMPT,
        checkpointer=checkpointer,
    )
