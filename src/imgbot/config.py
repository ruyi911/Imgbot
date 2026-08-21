from __future__ import annotations

from functools import lru_cache
from typing import Annotated
from zoneinfo import ZoneInfo

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    bot_token: str = Field(min_length=20)
    assistant_bot_token_1: str = Field(min_length=20)
    assistant_bot_token_2: str = Field(min_length=20)
    bot_instance_id: str = Field(min_length=1, max_length=64)
    database_url: str = "postgresql+asyncpg://imgbot:imgbot@postgres:5432/imgbot"
    super_admin_ids: Annotated[frozenset[int], NoDecode]
    business_timezone: str = "Asia/Kolkata"
    album_settle_seconds: float = Field(default=1.5, ge=0.5, le=10)
    min_group_reply_interval_seconds: float = Field(default=3.1, ge=1, le=60)
    min_combined_reply_interval_seconds: float = Field(default=1.05, ge=1, le=10)
    reply_poll_seconds: float = Field(default=0.5, ge=0.1, le=10)
    reply_max_attempts: int = Field(default=3, ge=1, le=3)
    reply_request_timeout_seconds: int = Field(default=3, ge=1, le=60)
    reply_sending_lease_seconds: float = Field(default=90, ge=10, le=600)
    log_level: str = "INFO"

    @field_validator("super_admin_ids", mode="before")
    @classmethod
    def parse_admin_ids(cls, value: object) -> object:
        if isinstance(value, str):
            values = [item.strip() for item in value.split(",") if item.strip()]
            if not values:
                raise ValueError("SUPER_ADMIN_IDS cannot be empty")
            return frozenset(int(item) for item in values)
        return value

    @field_validator("business_timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        ZoneInfo(value)
        return value

    @field_validator("database_url")
    @classmethod
    def validate_async_database_url(cls, value: str) -> str:
        if not value.startswith(("postgresql+asyncpg://", "sqlite+aiosqlite://")):
            raise ValueError("DATABASE_URL must use asyncpg or aiosqlite")
        return value

    @model_validator(mode="after")
    def validate_distinct_bot_tokens(self) -> Settings:
        tokens = {
            self.bot_token,
            self.assistant_bot_token_1,
            self.assistant_bot_token_2,
        }
        if len(tokens) != 3:
            raise ValueError("BOT_TOKEN and assistant bot tokens must be different")
        if self.reply_sending_lease_seconds < self.reply_request_timeout_seconds + 5:
            raise ValueError(
                "REPLY_SENDING_LEASE_SECONDS must be at least "
                "REPLY_REQUEST_TIMEOUT_SECONDS + 5"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
