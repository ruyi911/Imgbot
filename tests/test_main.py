from imgbot import main as main_module
from imgbot.config import Settings


async def test_build_bots_uses_independent_bounded_sessions(monkeypatch) -> None:
    monkeypatch.setenv("BOT_TOKEN", "123456789:abcdefghijklmnopqrstuvwxyz123456")
    monkeypatch.setenv(
        "ASSISTANT_BOT_TOKEN_1", "223456789:abcdefghijklmnopqrstuvwxyz123456"
    )
    monkeypatch.setenv(
        "ASSISTANT_BOT_TOKEN_2", "323456789:abcdefghijklmnopqrstuvwxyz123456"
    )
    monkeypatch.setenv("BOT_INSTANCE_ID", "test01")
    monkeypatch.setenv("SUPER_ADMIN_IDS", "123456789")
    settings = Settings()  # type: ignore[call-arg]

    bots = main_module.build_bots(settings)
    try:
        assert len({id(bot.session) for bot in bots}) == 3
        assert [bot.session.timeout for bot in bots] == [3.0, 3.0, 3.0]
    finally:
        for bot in bots:
            await bot.session.close()
