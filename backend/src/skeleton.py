"""Reduce HTML to a structural skeleton suitable for an LLM to study.

Goals:
- Drop noise: <style>, <svg>, <noscript>, <iframe>, comments, base64 imgs,
  external/large <script> bundles (jQuery, analytics, framework code).
- Keep small inline <script> bodies — these often hold pagination configs
  (e.g. `Pager({prefix:'index', suffix:'html'})`) or JSON-LD bits that
  are load-bearing for selector inference.
- Keep tag names, class/id attributes, href targets, and trimmed text.
- Truncate overlong text nodes — selector inference doesn't need full article bodies.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup, Comment, NavigableString, Tag


# script 单独处理(条件保留 inline 小脚本),不在 _DROP_TAGS 里。
_DROP_TAGS = {"style", "noscript", "svg", "iframe", "meta", "link"}
_KEEP_ATTRS_STRUCT = {"class", "id", "href", "name", "onclick", "data-href", "data-url"}
_HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
_TEXT_CHAR_BUDGET = 40
_TEXT_PLACEHOLDER = "_"
# inline <script> 内容超过这个长度判为 minified 大块,丢弃;低于则原样保留。
_INLINE_SCRIPT_MAX_CHARS = 500


def _trim_text(txt: str) -> str:
    txt = re.sub(r"\s+", " ", txt).strip()
    if len(txt) > _TEXT_CHAR_BUDGET:
        return txt[:_TEXT_CHAR_BUDGET] + "…"
    return txt


def _should_keep_script(tag: Tag) -> bool:
    """src 脚本(外链 JS)保留为空 body 标签,让 agent 看到文件名(JSON 模式定位 API 的关键);
    inline 短小 body 保留(常见 Pager 配置 / channelId 变量 / doT 模板)。
    inline 长 body / 空 body 都丢。"""
    if tag.get("src"):
        return True
    body = tag.string or "".join(
        c for c in tag.strings if isinstance(c, NavigableString)
    )
    if not body:
        return False
    body = body.strip()
    if not body:
        return False
    return len(body) <= _INLINE_SCRIPT_MAX_CHARS


def _serialize(node: Tag, out: list[str], depth: int, keep_text_in_headings: bool) -> None:
    indent = "  " * depth
    if node.name == "script":
        src = node.get("src")
        if src:
            # 外链 JS:输出空 body 标签,只露 src 路径。trim 跟 href 同套规则。
            src_str = str(src).split("?", 1)[0]
            if len(src_str) > 60:
                src_str = "…" + src_str[-60:]
            out.append(f'{indent}<script src="{src_str}"/>')
            return
        body = (node.string or "").strip()
        # 折成单行,让骨架紧凑
        body = re.sub(r"\s+", " ", body)
        out.append(f"{indent}<script>{body}</script>")
        return

    attrs = []
    keep_attrs = set(_KEEP_ATTRS_STRUCT)
    if keep_text_in_headings and node.name in _HEADING_TAGS:
        keep_attrs.add("title")
    for k in keep_attrs:
        v = node.get(k)
        if not v:
            continue
        if isinstance(v, list):
            v = " ".join(v)
        v = str(v)
        if k == "href":
            # Keep only a short trailing fragment so LLM sees the URL pattern,
            # not full sensitive paths.
            v = v.split("?", 1)[0]
            if len(v) > 60:
                v = "…" + v[-60:]
        elif len(v) > 120:
            v = v[:120] + "…"
        attrs.append(f'{k}="{v}"')
    attr_str = (" " + " ".join(attrs)) if attrs else ""

    direct_text_parts: list[str] = []
    for child in node.children:
        if isinstance(child, NavigableString) and not isinstance(child, Comment):
            t = _trim_text(str(child))
            if not t:
                continue
            if keep_text_in_headings and node.name in _HEADING_TAGS:
                direct_text_parts.append(t)
            else:
                direct_text_parts.append(_TEXT_PLACEHOLDER)
    direct_text = " ".join(direct_text_parts)

    has_element_children = any(isinstance(c, Tag) for c in node.children)

    if not has_element_children:
        if direct_text:
            out.append(f"{indent}<{node.name}{attr_str}>{direct_text}</{node.name}>")
        else:
            out.append(f"{indent}<{node.name}{attr_str}/>")
        return
    open_line = f"{indent}<{node.name}{attr_str}>"
    if direct_text:
        open_line += direct_text
    out.append(open_line)
    for child in node.children:
        if isinstance(child, Tag) and child.name not in _DROP_TAGS:
            _serialize(child, out, depth + 1, keep_text_in_headings)
    out.append(f"{indent}</{node.name}>")


def to_skeleton(html: str, max_chars: int = 40000, keep_text_in_headings: bool = True) -> str:
    soup = BeautifulSoup(html, "lxml")

    for tag_name in _DROP_TAGS:
        for t in soup.find_all(tag_name):
            t.decompose()
    # script 按规则筛:大块 / external 丢,inline 小段留。
    for s in soup.find_all("script"):
        if not _should_keep_script(s):
            s.decompose()
    for c in soup.find_all(string=lambda x: isinstance(x, Comment)):
        c.extract()

    root = soup.find("body") or soup
    if not isinstance(root, Tag):
        return ""

    lines: list[str] = []
    _serialize(root, lines, 0, keep_text_in_headings)
    text = "\n".join(lines)

    if len(text) > max_chars:
        head_share = int(max_chars * 0.7)
        tail_share = max_chars - head_share - 40
        text = (
            text[:head_share]
            + "\n... [skeleton truncated] ...\n"
            + text[-tail_share:]
        )
    return text
