from types import SimpleNamespace

from imgbot.filters import BotIdFilter


async def test_bot_id_filter_accepts_event_and_injected_bot() -> None:
    bot_filter = BotIdFilter({100, 200})

    assert await bot_filter(object(), bot=SimpleNamespace(id=100)) is True
    assert await bot_filter(object(), bot=SimpleNamespace(id=300)) is False
