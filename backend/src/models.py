from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class NewsItem(BaseModel):
    title: str
    url: str
    date: str | None = None


class NewsDetail(BaseModel):
    title: str | None = None
    date: str | None = None
    source: str | None = None
    content: str = ""


class NewsRecord(BaseModel):
    title: str
    url: str
    date: str | None = None
    detail: NewsDetail | None = None


class ListSelectors(BaseModel):
    """CSS selectors for extracting a list of news items from a list page."""

    container: str = Field(description="CSS selector for the <ul>/<div> wrapping items")
    item: str = Field(description="CSS selector for a single news item, relative to container")
    title: str = Field(description="CSS selector inside the item for title text")
    title_attr: Literal["text", "title"] = Field(default="text")
    url: str = Field(description="CSS selector inside the item for the link element")
    url_attr: str = Field(default="href")
    date: str | None = Field(default=None, description="CSS selector for date; null if not on list page")
    date_attr: Literal["text"] = Field(default="text")
    next_page_template: str | None = Field(
        default=None,
        description=(
            "URL pattern for pagination, with {n} as page number placeholder, e.g. 'index_{n}.html'. "
            "Null if pagination is not detectable."
        ),
    )


class DetailSelectors(BaseModel):
    """CSS selectors for extracting a single news detail page."""

    title: str | None = Field(default=None)
    date: str | None = Field(default=None)
    source: str | None = Field(default=None)
    content: str = Field(description="CSS selector for the main article body container")


class ExtractRequest(BaseModel):
    url: str
    section: str
    with_detail: bool = True
    max_items: int = 20


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None


# ===== API request/response schemas (subscription + session) =====


class SubscriptionCreateIn(BaseModel):
    alias: str
    url: str
    section: str


class SubscriptionOut(BaseModel):
    id: str
    alias: str
    url: str
    section: str
    last_refreshed_at: datetime | None = None
    item_count: int = 0
    created_at: datetime


class SubscriptionDetailOut(SubscriptionOut):
    list_selectors: ListSelectors
    detail_selectors: DetailSelectors | None = None


class NewsItemOut(BaseModel):
    id: int
    subscription_id: str
    url: str
    title: str
    pub_date: str | None = None
    source: str | None = None
    fetched_at: datetime


class NewsItemDetailOut(NewsItemOut):
    content: str = ""


class RefreshOut(BaseModel):
    added: int
    fetched: int


class SessionCreateIn(BaseModel):
    alias: str
    url: str
    section: str


class ChatMessageOut(BaseModel):
    role: Literal["user", "assistant", "tool", "system"]
    content: str = ""
    tool_calls: list[dict[str, Any]] | None = None
    tool_name: str | None = None


class SessionOut(BaseModel):
    id: str
    status: Literal["draft", "confirmed", "abandoned"]
    alias: str
    url: str
    section: str
    subscription_id: str | None = None
    messages: list[ChatMessageOut] = Field(default_factory=list)


class SessionCreateOut(BaseModel):
    session_id: str
    status: Literal["draft", "confirmed", "abandoned"] = "draft"


class SessionMessageIn(BaseModel):
    content: str


class SessionConfirmOut(BaseModel):
    subscription_id: str
