"""_parse_list 两条路径(CSS / JSON)的单测。

CSS 路径用一段嵌入 fixture HTML 跑 BeautifulSoup;JSON 路径 monkeypatch fetch_json 返回固定 dict,
验证字段映射、url 拼接、date 透传给 normalize_pub_date。
"""

from __future__ import annotations

from src import extractor
from src.models import ListSelectors


# ===== CSS path =====


_CSS_HTML = """
<!doctype html>
<html><body>
  <div class="page">
    <ul class="news-list">
      <li><a href="/news/2026/0501/abc.html">政府工作报告全文</a>
          <span class="date">2026-05-01</span></li>
      <li><a href="./0502/def.html">关于发布 ABC 通知的公告</a>
          <span class="date">2026-05-02</span></li>
      <li><a href="javascript:void(0)" onclick="jumpToDetail('/news/2026/0503/xyz.html')">某某文件</a>
          <span class="date">2026-05-03</span></li>
    </ul>
  </div>
</body></html>
"""


def test_parse_list_css_basic() -> None:
    sel = ListSelectors.model_validate({
        "container": "ul.news-list",
        "item": "li",
        "title": "a",
        "title_attr": "text",
        "url": "a",
        "url_attr": "href",
        "date": "span.date",
        "date_attr": "text",
    })
    items = extractor._parse_list_css(
        _CSS_HTML, "https://x.gov.cn/col/index.html", sel, max_items=10
    )
    # 第 3 条 href 是 javascript:void(0),没有 url_regex → 拿到的是字面量,urljoin 后是
    # 'https://x.gov.cn/col/javascript:void(0)' 这种垃圾,但仍会进 items(没强校验)。
    assert len(items) == 3
    assert items[0].title.startswith("政府工作报告")
    assert items[0].url == "https://x.gov.cn/news/2026/0501/abc.html"
    assert items[0].date == "2026-05-01"
    assert items[1].url == "https://x.gov.cn/col/0502/def.html"


def test_parse_list_css_with_url_regex_extracts_onclick() -> None:
    """url_attr=onclick + url_regex,从 onclick 字符串里抠 URL。"""
    sel = ListSelectors.model_validate({
        "container": "ul.news-list",
        "item": "li",
        "title": "a",
        "url": "a",
        "url_attr": "onclick",
        "url_regex": r"jumpToDetail\('([^']+)'\)",
        "date": "span.date",
    })
    items = extractor._parse_list_css(
        _CSS_HTML, "https://x.gov.cn/col/index.html", sel, max_items=10
    )
    # 只有第 3 条带 onclick,前两条 onclick 为空 → _extract_attr 返回 None → 跳过
    assert len(items) == 1
    assert items[0].url == "https://x.gov.cn/news/2026/0503/xyz.html"


def test_parse_list_css_max_items() -> None:
    sel = ListSelectors.model_validate({
        "container": "ul.news-list",
        "item": "li",
        "title": "a",
        "url": "a",
    })
    items = extractor._parse_list_css(_CSS_HTML, "https://x.gov.cn/", sel, max_items=2)
    assert len(items) == 2


def test_parse_list_top_dispatcher_css() -> None:
    sel = ListSelectors.model_validate({
        "container": "ul.news-list",
        "item": "li",
        "title": "a",
        "url": "a",
        "date": "span.date",
    })
    items = extractor._parse_list(_CSS_HTML, "https://x.gov.cn/col/", sel, max_items=10)
    assert len(items) == 3


# ===== JSON path =====


_HUNAN_JSON_FIXTURE = {
    "code": 0,
    "msg": "success",
    "data": {
        "total": 15606,
        "results": [
            {
                "id": "abc1",
                "title": "湖南省人民政府办公厅关于印发某某方案的通知",
                "url": "https://www.hunan.gov.cn/hnszf/xxgk/wjk/202605/t20260501_a.html",
                "publishedTimeStr": "2026-05-01 10:30:00",
                "content": "一、总体要求...（节选）",
            },
            {
                "id": "abc2",
                "title": "省政府新闻办举行某某新闻发布会",
                "url": "/hnszf/xxgk/wjk/202605/t20260502_b.html",
                "publishedTimeStr": "2026-05-02 14:00:00",
                "content": "5 月 2 日下午...",
            },
        ],
    },
}


def test_parse_list_json_maps_fields_and_urljoins(monkeypatch) -> None:
    captured: dict = {}

    def fake_fetch_json(endpoint, method="POST", body=None, *, base_url=None, referer=None):
        captured["endpoint"] = endpoint
        captured["method"] = method
        captured["body"] = body
        captured["base_url"] = base_url
        captured["referer"] = referer
        return _HUNAN_JSON_FIXTURE

    monkeypatch.setattr(extractor, "fetch_json", fake_fetch_json)

    sel = ListSelectors.model_validate({
        "mode": "json",
        "json_endpoint": "https://api.hunan.gov.cn/search/common/search/100782",
        "json_method": "POST",
        "json_body": {"datas[0][key]": "status", "datas[0][value]": "1", "page": "1"},
        "json_results_path": "data.results",
        "json_url_field": "url",
        "json_title_field": "title",
        "json_date_field": "publishedTimeStr",
        "json_page_param": "page",
        "json_page_start": 1,
        "date_patterns": ["%Y-%m-%d %H:%M:%S"],
        "date_output": "iso_datetime",
    })

    items = extractor._parse_list_json(
        "https://www.hunan.gov.cn/hnszf/hnyw/sy/hnyw1/gl_fgsjpx.html",
        sel,
        max_items=10,
        page=1,
    )

    assert len(items) == 2
    assert items[0].title.startswith("湖南省人民政府办公厅")
    assert items[0].url.startswith("https://www.hunan.gov.cn/")
    assert items[0].date == "2026-05-01 10:30:00"

    # 相对 url 应该被列表页 base_url urljoin
    assert items[1].url == "https://www.hunan.gov.cn/hnszf/xxgk/wjk/202605/t20260502_b.html"

    # body[page] 被翻页机制写入(page=1 → start + 0 = 1)
    assert captured["body"]["page"] == "1"
    # 其余 body 字段保留
    assert captured["body"]["datas[0][key]"] == "status"


def test_parse_list_json_pagination_writes_page_param(monkeypatch) -> None:
    captured: dict = {}

    def fake_fetch_json(endpoint, method="POST", body=None, *, base_url=None, referer=None):
        captured["body"] = dict(body or {})
        return {"data": {"results": []}}

    monkeypatch.setattr(extractor, "fetch_json", fake_fetch_json)

    sel = ListSelectors.model_validate({
        "mode": "json",
        "json_endpoint": "https://api.x.gov.cn/list",
        "json_body": {"channelId": "100"},
        "json_results_path": "data.results",
        "json_url_field": "url",
        "json_title_field": "title",
        "json_page_param": "page",
        "json_page_start": 1,
    })

    extractor._parse_list_json("https://x.gov.cn/", sel, max_items=10, page=3)
    # page 3 → page_start + (3-1) = 3
    assert captured["body"]["page"] == "3"
    assert captured["body"]["channelId"] == "100"


def test_parse_list_json_no_page_param_returns_empty_for_page_2(monkeypatch) -> None:
    """json_page_param=null 时 page>1 直接返回空,不应该再调 fetch_json。"""
    called = {"n": 0}

    def fake_fetch_json(*a, **kw):
        called["n"] += 1
        return {}

    monkeypatch.setattr(extractor, "fetch_json", fake_fetch_json)

    sel = ListSelectors.model_validate({
        "mode": "json",
        "json_endpoint": "https://api.x.gov.cn/list",
        "json_results_path": "data.results",
        "json_url_field": "url",
        "json_title_field": "title",
        "json_page_param": None,
    })
    items = extractor._parse_list_json("https://x.gov.cn/", sel, max_items=10, page=2)
    assert items == []
    assert called["n"] == 0


def test_parse_list_json_skips_items_with_missing_fields(monkeypatch) -> None:
    fixture = {
        "data": {
            "results": [
                {"title": "ok", "url": "/a"},
                {"title": "no url"},  # 跳过
                {"url": "/c"},  # 跳过
                {"title": "ok2", "url": "/d"},
            ]
        }
    }
    monkeypatch.setattr(extractor, "fetch_json", lambda *a, **kw: fixture)

    sel = ListSelectors.model_validate({
        "mode": "json",
        "json_endpoint": "https://api.x.gov.cn/list",
        "json_results_path": "data.results",
        "json_url_field": "url",
        "json_title_field": "title",
    })
    items = extractor._parse_list_json("https://x.gov.cn/", sel, max_items=10)
    assert [it.title for it in items] == ["ok", "ok2"]


def test_parse_list_top_dispatcher_json(monkeypatch) -> None:
    """顶层 _parse_list 在 mode=json 时不需要 html(传 None 也通)。"""
    monkeypatch.setattr(
        extractor, "fetch_json", lambda *a, **kw: _HUNAN_JSON_FIXTURE
    )
    sel = ListSelectors.model_validate({
        "mode": "json",
        "json_endpoint": "https://api.hunan.gov.cn/search/common/search/100782",
        "json_results_path": "data.results",
        "json_url_field": "url",
        "json_title_field": "title",
    })
    items = extractor._parse_list(None, "https://www.hunan.gov.cn/", sel, max_items=10)
    assert len(items) == 2
