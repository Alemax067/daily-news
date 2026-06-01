"""jpage / XML datastore 子分支单测。

覆盖:
- _decode_xml_datastore 抠 record CDATA 的正则正确性(内联 + 裸 XML)
- jcms 偶发 `<li style=<br/>` 碎屑容错
- _parse_list_css 在 xml_decode_datastore=True 时跑通,得到正确 NewsItem
- xml_decode_datastore=False(默认)对常规 HTML 不产生影响
- 老 schema 不带 xml_decode_datastore 字段 → model_validate 通过,默认 False
"""

from __future__ import annotations

from src import extractor
from src.models import ListSelectors


# ===== _decode_xml_datastore 直接测 =====


def test_decode_xml_datastore_inline_records() -> None:
    """完整 HTML 含内联 `<script type="text/xml">` → 抠出 3 条 li 串成合成 div。"""
    html = """
    <!doctype html><html><body>
    <ul class="main_list"></ul>
    <script type="text/xml"><datastore>
      <recordset>
        <record><![CDATA[
          <li><a href='/art/2026/6/1/a.html' title='标题1'>标题1</a><span>2026-06-01</span></li>
        ]]></record>
        <record><![CDATA[
          <li><a href='/art/2026/6/1/b.html' title='标题2'>标题2</a><span>2026-06-01</span></li>
        ]]></record>
        <record><![CDATA[
          <li><a href='/art/2026/5/31/c.html' title='标题3'>标题3</a><span>2026-05-31</span></li>
        ]]></record>
      </recordset>
    </datastore></script>
    </body></html>
    """
    out = extractor._decode_xml_datastore(html)
    assert out.startswith('<div id="__jpage_synth__">')
    assert out.count("<li>") + out.count("<li ") >= 3 or out.count("<li>") == 3 or "<li>" in out or "<li " in out
    # 简化:实际看 li href 数量
    assert out.count("href='/art/2026") == 3


def test_decode_xml_datastore_pure_xml_response() -> None:
    """裸 XML(模拟 dataproxy.jsp page 2+ 响应,没有 <html> 包裹)→ 同样抠出 records。"""
    xml = """<datastore>
      <totalrecord>3481</totalrecord>
      <totalpage>35</totalpage>
      <recordset>
        <record><![CDATA[<li><a href='/art/2026/5/7/x.html' title='X'>X</a><span>2026-05-07</span></li>]]></record>
        <record><![CDATA[<li><a href='/art/2026/5/6/y.html' title='Y'>Y</a><span>2026-05-06</span></li>]]></record>
      </recordset>
    </datastore>"""
    out = extractor._decode_xml_datastore(xml)
    assert out.count("href='/art/2026") == 2


def test_decode_xml_datastore_handles_jcms_artifacts() -> None:
    """jcms 偶尔在 record 末尾留 `<li style=<br/>` 碎屑;BeautifulSoup 仍能选到正确 li > a。"""
    from bs4 import BeautifulSoup

    xml = """<datastore><recordset>
      <record><![CDATA[<li><a href='/art/ok1.html' title='OK1'>OK1</a><span>2026-06-01</span></li><li style=<br/>]]></record>
      <record><![CDATA[<li><a href='/art/ok2.html' title='OK2'>OK2</a><span>2026-06-02</span></li>]]></record>
    </recordset></datastore>"""
    out = extractor._decode_xml_datastore(xml)
    soup = BeautifulSoup(out, "lxml")
    # container = 合成根 div
    container = soup.select_one("div#__jpage_synth__")
    assert container is not None
    # 真正能拿到链接的 li 数 = 2(碎屑 li 没 a)
    items = [li for li in container.select("li") if li.select_one("a")]
    assert len(items) == 2
    hrefs = [li.select_one("a").get("href") for li in items]
    assert hrefs == ["/art/ok1.html", "/art/ok2.html"]


def test_decode_xml_datastore_no_records_returns_empty() -> None:
    """非 jpage 页面(没有 record CDATA)→ 返回空字符串,上层视作无数据。"""
    html = "<html><body><ul><li><a href='/x'>x</a></li></ul></body></html>"
    out = extractor._decode_xml_datastore(html)
    assert out == ""


# ===== _parse_list_css 端到端 =====


_JIANGSU_LIKE_HTML = """
<!doctype html><html><body>
<div id="page">
  <ul class="main_list" style="margin-bottom:40px;"></ul>
</div>
<script type="text/xml"><datastore>
  <nextgroup><![CDATA[<a href="/module/web/jpage/dataproxy.jsp?page=1&columnid=60096"></a>]]></nextgroup>
  <recordset>
    <record><![CDATA[
      <li><a href='/art/2026/6/1/art_60096_11778517.html' title='聚焦健康' target="_blank">聚焦健康</a><span>2026-06-01</span></li>
    ]]></record>
    <record><![CDATA[
      <li><a href='/art/2026/6/1/art_60096_11778516.html' title='农村产权' target="_blank">农村产权</a><span>2026-06-01</span></li>
    ]]></record>
    <record><![CDATA[
      <li><a href='/art/2026/5/31/art_60096_11778353.html' title='港江苏总会' target="_blank">港江苏总会</a><span>2026-05-31</span></li>
    ]]></record>
  </recordset>
</datastore></script>
</body></html>
"""


def test_parse_list_css_with_xml_decode_extracts_records() -> None:
    sel = ListSelectors.model_validate({
        "mode": "css",
        "xml_decode_datastore": True,
        "container": "div#__jpage_synth__",
        "item": "li",
        "title": "a",
        "title_attr": "title",
        "url": "a",
        "url_attr": "href",
        "date": "span",
        "date_attr": "text",
    })
    items = extractor._parse_list_css(
        _JIANGSU_LIKE_HTML, "https://www.jiangsu.gov.cn/col/col60096/index.html", sel, max_items=10
    )
    assert len(items) == 3
    # title 走 title 属性
    assert items[0].title == "聚焦健康"
    # url 用列表页 base_url urljoin 成绝对地址
    assert items[0].url == "https://www.jiangsu.gov.cn/art/2026/6/1/art_60096_11778517.html"
    assert items[0].date == "2026-06-01"
    assert items[2].url == "https://www.jiangsu.gov.cn/art/2026/5/31/art_60096_11778353.html"


def test_parse_list_css_xml_decode_off_default_unaffected() -> None:
    """xml_decode_datastore 默认 False 时,_parse_list_css 跑普通 HTML 行为不变(回归保护)。"""
    plain_html = """
    <html><body>
      <ul class="news"><li><a href="/a.html">A</a><span>2026-06-01</span></li>
        <li><a href="/b.html">B</a><span>2026-05-31</span></li></ul>
    </body></html>
    """
    sel = ListSelectors.model_validate({
        "mode": "css",
        "container": "ul.news",
        "item": "li",
        "title": "a",
        "url": "a",
        "date": "span",
    })
    assert sel.xml_decode_datastore is False
    items = extractor._parse_list_css(plain_html, "https://x.gov.cn/", sel, max_items=10)
    assert len(items) == 2
    assert items[0].url == "https://x.gov.cn/a.html"


def test_parse_list_css_xml_decode_pure_xml_response() -> None:
    """模拟 dataproxy.jsp page 2 响应(裸 XML)经 xml_decode 后能跑出 items。"""
    xml = """<datastore><recordset>
      <record><![CDATA[<li><a href='/art/p2_a.html' title='P2A'>P2A</a><span>2026-05-07</span></li>]]></record>
      <record><![CDATA[<li><a href='/art/p2_b.html' title='P2B'>P2B</a><span>2026-05-06</span></li>]]></record>
    </recordset></datastore>"""
    sel = ListSelectors.model_validate({
        "mode": "css",
        "xml_decode_datastore": True,
        "container": "div#__jpage_synth__",
        "item": "li",
        "title": "a",
        "title_attr": "title",
        "url": "a",
        "date": "span",
    })
    items = extractor._parse_list_css(
        xml, "https://www.jiangsu.gov.cn/col/col60096/index.html", sel, max_items=10
    )
    assert len(items) == 2
    assert items[0].title == "P2A"
    assert items[0].url == "https://www.jiangsu.gov.cn/art/p2_a.html"


# ===== 迁移性 =====


def test_legacy_row_without_xml_decode_field_validates() -> None:
    """老 row 没有 xml_decode_datastore 字段 → pydantic 默认填 False,不影响行为。"""
    legacy = {
        "container": "ul.news",
        "item": "li",
        "title": "a",
        "url": "a",
    }
    sel = ListSelectors.model_validate(legacy)
    assert sel.mode == "css"
    assert sel.xml_decode_datastore is False
    # roundtrip 不丢字段
    dumped = sel.model_dump()
    assert dumped["xml_decode_datastore"] is False
