"""commit_selectors("list") 的 SSL/URL 硬门回归测试。

防回归点:agent 不能靠偷换 http↔https 协议绕过 SSL 错误后用原 URL 落库。
代码门由 cache.CacheStore._session_url_fetched_ok 实现,fetch_skeleton /
try_list_selectors 命中会话 URL 才翻 True;commit_selectors(list) 检查到 False 直接拒绝。
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest

from src import agent as agent_mod
from src import cache as cache_mod


# ===== flag 在 store 上的基本行为 =====


def test_file_store_flag_default_false() -> None:
    s = cache_mod.FileCacheStore()
    assert s.is_session_url_fetched() is False
    s.mark_session_url_fetched()
    assert s.is_session_url_fetched() is True


def test_two_session_stores_independent() -> None:
    """两个 SessionDBCacheStore 实例的 flag 互不影响(每次会话新建)。"""
    s1 = cache_mod.SessionDBCacheStore("sid1", ":memory:")
    s2 = cache_mod.SessionDBCacheStore("sid2", ":memory:")
    s1.mark_session_url_fetched()
    assert s1.is_session_url_fetched() is True
    assert s2.is_session_url_fetched() is False


# ===== 端到端:commit_selectors(list) 真的会拒 =====


@pytest.fixture
def session_db() -> tuple[str, str]:
    """造一个临时 sqlite,塞一行 chat_sessions(模拟 SSL 撞墙的湖南站)。"""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    db_path = tmp.name
    session_id = "test-session-ssl"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE chat_sessions (
              id TEXT PRIMARY KEY,
              url TEXT NOT NULL,
              section TEXT NOT NULL,
              list_selectors_json TEXT,
              detail_selectors_json TEXT
            )
            """
        )
        conn.execute(
            "INSERT INTO chat_sessions (id, url, section) VALUES (?, ?, ?)",
            (session_id, "https://www.hunan.gov.cn/list.html", "要闻"),
        )
        conn.commit()
    finally:
        conn.close()
    yield session_id, db_path
    Path(db_path).unlink(missing_ok=True)


_VALID_LIST_SELECTORS = {
    "mode": "css",
    "container": "ul.news",
    "item": "li",
    "title": "a",
    "url": "a",
    "date": None,
}


def test_commit_list_refused_when_session_url_never_fetched(session_db, monkeypatch) -> None:
    """模拟 SSL 错误场景:fetch_skeleton 全部抛异常 → flag 留 False → commit 被拒。"""
    session_id, db_path = session_db

    def boom(url: str) -> str:
        raise RuntimeError("[SSL: BAD_ECPOINT] bad ecpoint (_ssl.c:1032)")

    monkeypatch.setattr(agent_mod, "fetch_html", boom)

    with cache_mod.session_store(session_id, db_path):
        # agent 试着用 http 偷换协议「诊断」(会成功,因为 monkeypatch 让 https 也失败,
        # 但这里我们直接验:**不调 fetch_skeleton 也能 commit?** → 必须拒绝)
        out = agent_mod.commit_selectors.invoke({
            "target": "list",
            "url": "https://www.hunan.gov.cn/list.html",
            "selectors": _VALID_LIST_SELECTORS,
            "section": "要闻",
        })
        assert "error" in out
        assert "从未被" in out["error"] or "fetch_skeleton" in out["error"]


def test_commit_list_refused_after_protocol_swap_fetch(session_db, monkeypatch) -> None:
    """关键场景:agent 用 http 协议跑通 fetch_skeleton(诊断),
    但 commit 用原 https URL → flag 仍为 False(因为抓的是 http 不是会话 URL),
    commit 被拒。这是当前 bug 的核心场景。"""
    session_id, db_path = session_db
    # 任何 url(http 或 https)fetch 都返回假 HTML
    monkeypatch.setattr(agent_mod, "fetch_html", lambda url: "<html><body><ul class='news'></ul></body></html>")

    with cache_mod.session_store(session_id, db_path):
        # agent 把 https 换成 http「诊断」
        agent_mod.fetch_skeleton.invoke({"url": "http://www.hunan.gov.cn/list.html"})
        # 然后试图用原 https URL commit
        out = agent_mod.commit_selectors.invoke({
            "target": "list",
            "url": "https://www.hunan.gov.cn/list.html",
            "selectors": _VALID_LIST_SELECTORS,
            "section": "要闻",
        })
        assert "error" in out
        assert "https://www.hunan.gov.cn/list.html" in out["error"]


def test_commit_list_passes_after_fetch_skeleton_on_session_url(session_db, monkeypatch) -> None:
    """正常路径:fetch_skeleton 用会话 URL 抓到 → flag=True → commit 放行。"""
    session_id, db_path = session_db
    monkeypatch.setattr(agent_mod, "fetch_html", lambda url: "<html><body><ul class='news'></ul></body></html>")

    with cache_mod.session_store(session_id, db_path):
        agent_mod.fetch_skeleton.invoke({"url": "https://www.hunan.gov.cn/list.html"})
        out = agent_mod.commit_selectors.invoke({
            "target": "list",
            "url": "https://www.hunan.gov.cn/list.html",
            "selectors": _VALID_LIST_SELECTORS,
            "section": "要闻",
        })
        assert out.get("ok") is True


def test_commit_list_passes_after_try_list_on_session_url(session_db, monkeypatch) -> None:
    """try_list_selectors 也是合法的 mark 入口(走 CSS 模式时要 fetch_html)。"""
    session_id, db_path = session_db
    monkeypatch.setattr(
        agent_mod,
        "fetch_html",
        lambda url: "<html><body><ul class='news'><li><a href='/x.html'>x</a></li></ul></body></html>",
    )
    # extractor 也通过 fetch_html 同名 import,保险起见也 patch 一下
    from src import extractor as extractor_mod
    monkeypatch.setattr(extractor_mod, "fetch_html", lambda url: "<html><body><ul class='news'><li><a href='/x.html'>x</a></li></ul></body></html>")

    with cache_mod.session_store(session_id, db_path):
        agent_mod.try_list_selectors.invoke({
            "url": "https://www.hunan.gov.cn/list.html",
            "selectors": _VALID_LIST_SELECTORS,
            "max_items": 3,
        })
        out = agent_mod.commit_selectors.invoke({
            "target": "list",
            "url": "https://www.hunan.gov.cn/list.html",
            "selectors": _VALID_LIST_SELECTORS,
            "section": "要闻",
        })
        assert out.get("ok") is True


def test_cli_mode_no_session_no_gate(monkeypatch) -> None:
    """文件后端(CLI)session_target() 返回 None,SSL gate 不应触发。"""
    # 默认 _store 是 FileCacheStore,session_target() = None
    # commit_selectors 在 sess is None 分支不进 SSL 检查
    monkeypatch.setattr(agent_mod, "fetch_html", lambda url: "<html></html>")
    out = agent_mod.commit_selectors.invoke({
        "target": "list",
        "url": "https://example.com/list.html",
        "selectors": _VALID_LIST_SELECTORS,
        "section": "x",
    })
    # 没会话 → 直接落到默认 FileCacheStore,不应被 SSL 门拒
    assert out.get("ok") is True
