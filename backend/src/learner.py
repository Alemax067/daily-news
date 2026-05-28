"""LLM-driven CSS-selector learning.

Given an HTML skeleton + a section name (or a content goal), ask the LLM to
return JSON describing how to extract a news list (or news detail).

Uses langchain_openai.ChatOpenAI configured against any OpenAI-compatible
endpoint via DAILY_NEWS_AGENT_BASE_URL.
"""

from __future__ import annotations

import json
import re

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from .config import get_settings
from .models import DetailSelectors, ListSelectors


_LIST_SYSTEM = """You analyze an HTML skeleton from a Chinese government news \
portal and return CSS selectors that extract one specific news list section.

The skeleton has been redacted: most text nodes are replaced with `_` to keep \
the request small and content-neutral. Only headings (h1-h6) keep their text, \
which lets you locate the right section by its <h2>/<h3>/<h4> label.

Output strict JSON only — no prose, no markdown fence.

Schema:
{
  "container":  "<CSS selector for the wrapper element holding the list items>",
  "item":       "<CSS selector for a single news item, relative to container>",
  "title":      "<CSS selector inside item for the title element>",
  "title_attr": "text" | "title",
  "url":        "<CSS selector inside item for the link element>",
  "url_attr":   "href",
  "date":       "<CSS selector inside item for date, or null if not present>",
  "date_attr":  "text",
  "next_page_template": "<URL pattern for pagination with {n} as page number, e.g. 'index_{n}.html', or null>"
}

Rules:
- Match the section by the heading text near the candidate list (e.g. an <h3> with text "上海要闻" right above a <ul>).
- Prefer specific selectors using class names; keep them short. Avoid `:nth-child(...)` unless unavoidable.
- `container` must be unique within the page; combine class names if needed.
- `item` is RELATIVE to container — usually just `li` or `dl` or `div.item`.
- Since text content is redacted, prefer `title_attr: "title"` when items expose a `title="…"` attribute on the link, otherwise use `"text"`.
- For `next_page_template`: look at href patterns of pagination links if visible, else return null.
"""


_DETAIL_SYSTEM = """You analyze an HTML skeleton from a Chinese news article \
detail page and return CSS selectors that extract its title, date, source, and body.

The skeleton has been redacted: most text nodes are replaced with `_`. Only \
headings (h1-h6) keep their text. Use tag/class/id structure to locate fields.

Output strict JSON only — no prose, no markdown fence.

Schema:
{
  "title":   "<CSS selector for the article title element, or null>",
  "date":    "<CSS selector for the publish date element, or null>",
  "source":  "<CSS selector for the source/origin element, or null>",
  "content": "<CSS selector for the main article body container — REQUIRED>"
}

Rules:
- `content` is required. Pick the broadest container holding article paragraphs (e.g. `#mainText`, `.TRS_Editor`, `.article-content`, `.view`).
- Title is typically inside `.header h1` or `.article-title`.
- Date and source are often siblings inside one header line; pick the closest unique selector.
- Selectors must be valid CSS, no XPath, no `:contains()`.
"""


def _build_chat() -> ChatOpenAI:
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


def _strip_fence(text: str) -> str:
    text = text.strip()
    m = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, flags=re.DOTALL)
    return m.group(1).strip() if m else text


def _invoke_json(system_prompt: str, user_content: str) -> dict:
    chat = _build_chat()
    resp = chat.invoke(
        [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_content),
        ]
    )
    raw = resp.content if isinstance(resp.content, str) else str(resp.content)
    return json.loads(_strip_fence(raw))


def learn_list_selectors(skeleton: str, section: str, page_url: str) -> ListSelectors:
    user = (
        f"Page URL: {page_url}\n"
        f"Section name (in Chinese): {section}\n\n"
        f"HTML skeleton:\n{skeleton}\n"
    )
    data = _invoke_json(_LIST_SYSTEM, user)
    return ListSelectors.model_validate(data)


def learn_detail_selectors(skeleton: str, page_url: str) -> DetailSelectors:
    user = (
        f"Page URL: {page_url}\n\n"
        f"HTML skeleton:\n{skeleton}\n"
    )
    data = _invoke_json(_DETAIL_SYSTEM, user)
    return DetailSelectors.model_validate(data)
