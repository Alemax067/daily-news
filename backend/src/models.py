from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, Field, PlainSerializer, model_validator


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
    """Selectors for extracting a list of news items from a list page.

    Two抓取模式:
      mode='css'  — 传统 HTML + CSS 选择器,大多数政府站走这条
      mode='json' — 站点用 doT.js / Vue 模板渲染,数据来自后端 JSON API。
                    agent 通过 fetch_text 读外链 JS 找到 endpoint,直接 POST/GET
                    拿 JSON,字段映射靠 json_*_field。

    迁移兼容:旧 row 没有 mode 字段时 pydantic 默认填 "css";老 schema 的
    container/item/title/url 都在,通过 mode='css' 必填校验。
    """

    mode: Literal["css", "json"] = Field(default="css")

    # ===== CSS mode 字段(放宽为 Optional;mode='css' 下由 validator 强制) =====
    container: str | None = Field(
        default=None,
        description="CSS selector for the <ul>/<div> wrapping items (mode='css' required)",
    )
    item: str | None = Field(
        default=None,
        description="CSS selector for a single news item, relative to container (mode='css' required)",
    )
    title: str | None = Field(
        default=None,
        description="CSS selector inside the item for title text (mode='css' required)",
    )
    title_attr: Literal["text", "title"] = Field(default="text")
    url: str | None = Field(
        default=None,
        description="CSS selector inside the item for the link element (mode='css' required)",
    )
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
    next_page_template: str | None = Field(
        default=None,
        description=(
            "(mode='css' only) URL pattern for pagination, with {n} as page number, "
            "e.g. 'index_{n}.html'. Null if pagination is not detectable."
        ),
    )
    next_page_start: int = Field(
        default=2,
        ge=0,
        description=(
            "(mode='css' only) Value of {n} that produces page 2's URL. Most sites use 2 "
            "(page 2 = index_2.html); some use 1 (page 2 = index_1.html, "
            "index_2.html is page 3). Page N's index = next_page_start + (N - 2). "
            "Ignored when next_page_template is null."
        ),
    )

    # ===== JSON mode 字段(mode='json' 下由 validator 强制必填的几个) =====
    json_endpoint: str | None = Field(
        default=None,
        description=(
            "(mode='json') 完整 URL 或相对路径(相对路径时 urljoin 列表页 URL)。"
            "agent 应当从外链 JS 源码里抠出来,把 channelId 等变量替换为真值。"
        ),
    )
    json_method: Literal["GET", "POST"] = Field(default="POST")
    json_body: dict[str, str] | None = Field(
        default=None,
        description=(
            "(mode='json') form-encoded body 字段(POST)或 query 参数(GET)。"
            "jQuery 数组写法直接展平,如 'datas[0][key]': 'status'。"
        ),
    )
    json_results_path: str | None = Field(
        default=None,
        description="(mode='json') 点路径定位 results 数组,如 'data.results'。",
    )
    json_url_field: str | None = Field(
        default=None,
        description="(mode='json') results[i] 里取 url 的字段名,如 'url'。",
    )
    json_url_prefix: str = Field(
        default="",
        description="(mode='json') 拼到 results[i][json_url_field] 前的固定前缀(很少用)。",
    )
    json_title_field: str | None = Field(
        default=None,
        description="(mode='json') results[i] 里取 title 的字段名,如 'title'。",
    )
    json_date_field: str | None = Field(
        default=None,
        description="(mode='json') results[i] 里取 date 的字段名,如 'publishedTimeStr';null 表示 list 不带日期。",
    )
    json_page_param: str | None = Field(
        default=None,
        description="(mode='json') body 里翻页字段名,如 'page' / 'pageNum'。null 表示无翻页。",
    )
    json_page_start: int = Field(
        default=1,
        ge=0,
        description="(mode='json') page 1 对应 json_page_param 的取值;多数 API 是 1。",
    )

    # ===== 共用 =====
    date_patterns: list[str] | None = Field(
        default=None,
        description=(
            "strptime format strings tried in order; first match wins. "
            "Required by commit_selectors when `date` (CSS) or `json_date_field` (JSON) is non-null."
        ),
    )
    date_output: Literal["iso_date", "iso_datetime"] | None = Field(
        default=None,
        description="Normalized output: 'iso_date' → YYYY-MM-DD, 'iso_datetime' → YYYY-MM-DD HH:MM:SS.",
    )

    @model_validator(mode="after")
    def _check_mode_required(self) -> Self:
        if self.mode == "css":
            missing = [
                f for f in ("container", "item", "title", "url")
                if getattr(self, f) in (None, "")
            ]
            if missing:
                raise ValueError(
                    f"mode='css' 必填字段缺失: {missing}"
                )
        else:  # mode == 'json'
            missing = [
                f for f in (
                    "json_endpoint",
                    "json_results_path",
                    "json_url_field",
                    "json_title_field",
                )
                if getattr(self, f) in (None, "")
            ]
            if missing:
                raise ValueError(
                    f"mode='json' 必填字段缺失: {missing}"
                )
        return self


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
