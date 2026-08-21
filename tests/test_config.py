import pytest
from pydantic import ValidationError

from imgbot.config import Settings


def set_bot_tokens(monkeypatch) -> None:
    monkeypatch.setenv("BOT_TOKEN", "123456789:abcdefghijklmnopqrstuvwxyz123456")
    monkeypatch.setenv(
        "ASSISTANT_BOT_TOKEN_1", "223456789:abcdefghijklmnopqrstuvwxyz123456"
    )
    monkeypatch.setenv(
        "ASSISTANT_BOT_TOKEN_2", "323456789:abcdefghijklmnopqrstuvwxyz123456"
    )


def test_comma_separated_super_admin_ids(monkeypatch) -> None:
    set_bot_tokens(monkeypatch)
    monkeypatch.setenv("BOT_INSTANCE_ID", "test01")
    monkeypatch.setenv("SUPER_ADMIN_IDS", "123456789,987654321")
    settings = Settings()  # type: ignore[call-arg]
    assert settings.super_admin_ids == frozenset({123456789, 987654321})
    assert settings.min_combined_reply_interval_seconds == 1.05
    assert settings.reply_max_attempts == 3
    assert settings.reply_request_timeout_seconds == 3
    assert settings.reply_sending_lease_seconds == 90


def test_reply_attempts_cannot_exceed_three(monkeypatch) -> None:
    set_bot_tokens(monkeypatch)
    monkeypatch.setenv("BOT_INSTANCE_ID", "test01")
    monkeypatch.setenv("SUPER_ADMIN_IDS", "123456789")
    monkeypatch.setenv("REPLY_MAX_ATTEMPTS", "4")

    with pytest.raises(ValidationError):
        Settings()  # type: ignore[call-arg]
