from __future__ import annotations

from collections.abc import Collection

from aiogram import Bot
from aiogram.filters import Filter


class BotIdFilter(Filter):
    def __init__(self, bot_ids: Collection[int]) -> None:
        self.bot_ids = frozenset(bot_ids)

    async def __call__(self, event: object, bot: Bot) -> bool:
        return bot.id in self.bot_ids
