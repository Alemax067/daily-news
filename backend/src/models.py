from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, PlainSerializer


def _utc_iso(v: datetime | None) -> str | None:
    """Serialize datetime as ISO8601 with explicit UTC offset.

    SQLite drops tzinfo on round-trip, so anything coming back from the DB is
    naive. We stored UTC via _now(); attach UTC here so the browser parses it
    correctly instead of assuming local time.
    """
    if v is None:
        return None
    if v.tzinfo is None:
        v = v.replace(tzinfo=timezone.utc)
    return v.astimezone(timezone.utc).isoformat()


UtcDatetime = Annotated[datetime, PlainSerializer(_utc_iso, return_type=str, when_used="json")]


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
    url_regex: str | None = Field(
        default=None,
        description=(
            "Optional regex applied to the extracted attribute value; group 1 "
            "is the real URL. Use when href is a JS placeholder and the real "
            "URL lives inside onclick (e.g. r\"jumpToDetail\\('([^']+)'\\)\")."
        ),
    )
    date: str | None = Field(default=None, description="CSS selector for date; null if not on list page")
    date_attr: Literal["text"] = Field(default="text")
    date_patterns: list[str] | None = Field(
        default=None,
        description=(
            "strptime format strings tried in order; first match wins. "
            "Required by commit_selectors when `date` is non-null."
        ),
    )
    date_output: Literal["iso_date", "iso_datetime"] | None = Field(
        default=None,
        description="Normalized output: 'iso_date' → YYYY-MM-DD, 'iso_datetime' → YYYY-MM-DD HH:MM:SS.",
    )
    next_page_template: str | None = Field(
        default=None,
        description=(
            "URL pattern for pagination, with {n} as page number placeholder, e.g. 'index_{n}.html'. "
            "Null if pagination is not detectable."
        ),
    )
    next_page_start: int = Field(
        default=2,
        ge=0,
        description=(
            "Value of {n} that produces page 2's URL. Most sites use 2 "
            "(page 2 = index_2.html); some use 1 (page 2 = index_1.html, "
            "index_2.html is page 3). Page N's index = next_page_start + (N - 2). "
            "Ignored when next_page_template is null."
        ),
    )


class DetailSelectors(BaseModel):
    """CSS selectors for extracting a single news detail page."""

    title: str | None = Field(default=None)
    date: str | None = Field(default=None)
    source: str | None = Field(default=None)
    content: str = Field(description="CSS selector for the main article body container")
    date_patterns: list[str] | None = Field(
        default=None,
        description="strptime format strings tried in order; first match wins.",
    )
    date_output: Literal["iso_date", "iso_datetime"] | None = Field(
        default=None,
        description="'iso_date' → YYYY-MM-DD, 'iso_datetime' → YYYY-MM-DD HH:MM:SS.",
    )


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
    auto_enabled: bool = True
    # 自动化路径:由 scheduler worker 写入,展示在 /automation 页
    last_refreshed_at: UtcDatetime | None = None
    item_count: int = 0
    # 订阅管理路径:由 refresh-preview 写入,展示在 /subscriptions 页
    preview_refreshed_at: UtcDatetime | None = None
    preview_item_count: int = 0
    created_at: UtcDatetime


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
    fetched_at: UtcDatetime


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
    is_streaming: bool = False
    messages: list[ChatMessageOut] = Field(default_factory=list)


class SessionCreateOut(BaseModel):
    session_id: str
    status: Literal["draft", "confirmed", "abandoned"] = "draft"


class SessionMessageIn(BaseModel):
    content: str


class SessionConfirmOut(BaseModel):
    subscription_id: str


class UpdateFromSessionIn(BaseModel):
    session_id: str


class SessionLookupOut(BaseModel):
    session_id: str | None = None


# ===== automation: settings + tasks =====


class SubscriptionPatchIn(BaseModel):
    auto_enabled: bool


class AppSettingsOut(BaseModel):
    trigger_time: str
    interval_hours: int
    new_sub_strategy: Literal["first_n", "since_days"]
    new_sub_n: int
    last_auto_run_at: UtcDatetime | None = None


class AppSettingsIn(BaseModel):
    trigger_time: str
    interval_hours: int
    new_sub_strategy: Literal["first_n", "since_days"]
    new_sub_n: int


class FetchTaskOut(BaseModel):
    id: int
    subscription_id: str
    subscription_alias: str | None = None
    status: Literal["pending", "running", "succeeded", "failed"]
    source: Literal["manual", "auto"]
    enqueued_at: UtcDatetime
    started_at: UtcDatetime | None = None
    finished_at: UtcDatetime | None = None
    items_added: int | None = None
    items_fetched: int | None = None
    pages_fetched: int | None = None
    stop_reason: str | None = None
    error: str | None = None


class TriggerAutomationOut(BaseModel):
    enqueued: int


class TimelineSubscriptionOut(BaseModel):
    """单条 run 内某个订阅的状态。只在 timeline 列出 items_added > 0 的订阅。"""

    subscription_id: str
    subscription_alias: str | None = None
    task_id: int
    status: Literal["pending", "running", "succeeded", "failed"]
    items_added: int


class TimelineRunOut(BaseModel):
    """一次触发(auto 或 manual)的聚合视图,timeline 的基本展示单元。"""

    run_id: str
    source: Literal["auto", "manual"]
    triggered_at: UtcDatetime
    task_count: int
    finished_count: int
    succeeded_count: int
    failed_count: int
    total_items_added: int
    subscriptions: list[TimelineSubscriptionOut] = Field(default_factory=list)


class TimelineExportItemOut(BaseModel):
    pub_date: str | None = None
    title: str
    url: str
    fetched_at: UtcDatetime


class TimelineExportGroupOut(BaseModel):
    """导出 xlsx 用的分组:一个订阅一组,内含本次触发新增的条目。"""

    subscription_id: str
    subscription_alias: str | None = None
    task_id: int
    items_added: int
    items: list[TimelineExportItemOut] = Field(default_factory=list)


class TimelineExportOut(BaseModel):
    run_id: str
    source: Literal["auto", "manual"]
    triggered_at: UtcDatetime
    total_items_added: int
    groups: list[TimelineExportGroupOut] = Field(default_factory=list)


class QueueSnapshotOut(BaseModel):
    running: FetchTaskOut | None = None
    pending: list[FetchTaskOut] = Field(default_factory=list)
    recent_done: list[FetchTaskOut] = Field(default_factory=list)
