from imgbot.config import Settings


def test_comma_separated_super_admin_ids(monkeypatch) -> None:
    monkeypatch.setenv("BOT_TOKEN", "123456789:abcdefghijklmnopqrstuvwxyz123456")
    monkeypatch.setenv("BOT_INSTANCE_ID", "test01")
    monkeypatch.setenv("SUPER_ADMIN_IDS", "123456789,987654321")
    settings = Settings()  # type: ignore[call-arg]
    assert settings.super_admin_ids == frozenset({123456789, 987654321})
