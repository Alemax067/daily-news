from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"
SELECTOR_CACHE_PATH = DATA_DIR / "selectors.json"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        env_prefix="DAILY_NEWS_AGENT_",
        env_ignore_empty=True,
        extra="ignore",
    )

    model: str = Field(default="deepseek-v4-pro")
    api_key: str = Field(default="")
    base_url: str = Field(default="https://yunwu.ai/v1")
    temperature: float = Field(default=0.2)
    max_tokens: int = Field(default=65536)
    timeout: int = Field(default=300)
    max_retries: int = Field(default=2)
    extra_body: dict[str, Any] = Field(default_factory=dict)

    fetch_timeout: int = Field(default=20)
    fetch_user_agent: str = Field(
        default=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0 Safari/537.36"
        )
    )

    list_skeleton_max_chars: int = Field(default=40000)
    detail_skeleton_max_chars: int = Field(default=30000)

    @field_validator("extra_body", mode="before")
    @classmethod
    def _parse_extra_body(cls, v: Any) -> Any:
        if v is None or v == "":
            return {}
        if isinstance(v, str):
            return json.loads(v)
        return v


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
        DATA_DIR.mkdir(parents=True, exist_ok=True)
    return _settings
