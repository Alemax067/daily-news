"""ListSelectors 迁移性单测:验证旧 row(没有 mode 字段)与新 JSON 模式 row 都能 model_validate。

DB schema 不动,list_selectors_json 是 opaque TEXT;新代码必须直接吃下旧 dump 出来的字符串。
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.models import ListSelectors


def test_legacy_css_row_validates_with_default_mode() -> None:
    """旧 schema(没有 mode 字段)→ pydantic 默认填 "css",所有原字段保留。"""
    legacy = {
        "container": "ul.news-list",
        "item": "li",
        "title": "a",
        "title_attr": "text",
        "url": "a",
        "url_attr": "href",
        "url_regex": None,
        "date": "span.date",
        "date_attr": "text",
        "date_patterns": ["%Y-%m-%d"],
        "date_output": "iso_date",
        "next_page_template": "index_{n}.html",
        "next_page_start": 2,
    }
    sel = ListSelectors.model_validate(legacy)
    assert sel.mode == "css"
    assert sel.container == "ul.news-list"
    assert sel.item == "li"
    assert sel.title == "a"
    assert sel.url == "a"
    assert sel.next_page_template == "index_{n}.html"
    assert sel.next_page_start == 2
    # JSON 字段全为默认 None / 默认空
    assert sel.json_endpoint is None
    assert sel.json_results_path is None
    assert sel.json_url_field is None
    assert sel.json_title_field is None
    assert sel.json_page_param is None


def test_legacy_css_dump_roundtrip_includes_mode() -> None:
    """旧 row 经过 model_validate → model_dump 后,新字段全部出现且不影响内容。"""
    legacy = {
        "container": ".list",
        "item": "li",
        "title": "a",
        "url": "a",
    }
    sel = ListSelectors.model_validate(legacy)
    dumped = sel.model_dump()
    assert dumped["mode"] == "css"
    assert dumped["container"] == ".list"
    # JSON 字段 dump 出来全是 None / 空 / 默认值
    assert dumped["json_endpoint"] is None
    assert dumped["json_method"] == "POST"
    assert dumped["json_page_start"] == 1
    # 二次 validate 应该等价
    sel2 = ListSelectors.model_validate(dumped)
    assert sel2 == sel


def test_json_mode_validates_with_required_fields() -> None:
    payload = {
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
    }
    sel = ListSelectors.model_validate(payload)
    assert sel.mode == "json"
    assert sel.json_endpoint == "https://api.hunan.gov.cn/search/common/search/100782"
    assert sel.json_results_path == "data.results"
    # CSS 字段全为 None
    assert sel.container is None
    assert sel.item is None
    assert sel.title is None
    assert sel.url is None


def test_css_mode_missing_required_field_rejected() -> None:
    bad = {
        "mode": "css",
        "container": "ul",
        # 缺 item / title / url
    }
    with pytest.raises(ValidationError):
        ListSelectors.model_validate(bad)


def test_json_mode_missing_endpoint_rejected() -> None:
    bad = {
        "mode": "json",
        "json_results_path": "data.results",
        "json_url_field": "url",
        "json_title_field": "title",
        # 缺 json_endpoint
    }
    with pytest.raises(ValidationError):
        ListSelectors.model_validate(bad)


def test_json_mode_missing_results_path_rejected() -> None:
    bad = {
        "mode": "json",
        "json_endpoint": "https://api.x.gov.cn/list",
        "json_url_field": "url",
        "json_title_field": "title",
    }
    with pytest.raises(ValidationError):
        ListSelectors.model_validate(bad)
