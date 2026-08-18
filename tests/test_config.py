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
