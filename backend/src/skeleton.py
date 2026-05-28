"""Reduce HTML to a structural skeleton suitable for an LLM to study.

Goals:
- Drop noise: <script>, <style>, <svg>, <noscript>, <iframe>, comments, base64 imgs.
- Keep tag names, class/id attributes, href targets, and trimmed text.
- Truncate overlong text nodes — selector inference doesn't need full article bodies.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup, Comment, NavigableString, Tag


_DROP_TAGS = {"script", "style", "noscript", "svg", "iframe", "meta", "link"}
_KEEP_ATTRS_STRUCT = {"class", "id", "href", "name"}
_HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
_TEXT_CHAR_BUDGET = 40
_TEXT_PLACEHOLDER = "_"


def _trim_text(txt: str) -> str:
    txt = re.sub(r"\s+", " ", txt).strip()
    if len(txt) > _TEXT_CHAR_BUDGET:
        return txt[:_TEXT_CHAR_BUDGET] + "…"
    return txt


def _serialize(node: Tag, out: list[str], depth: int, keep_text_in_headings: bool) -> None:
    indent = "  " * depth
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
