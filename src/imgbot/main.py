from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from imgbot.config import get_settings
from imgbot.db import Database
from imgbot.handlers import admin_router, group_router, utility_router
from imgbot.service import BotService
from imgbot.worker import ReplyWorker

logger = logging.getLogger(__name__)


async def main() -> None:
    settings = get_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    database = Database(settings.database_url)
    await database.create_schema()

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    me = await bot.get_me()
    service = BotService(
        database.sessions,
        instance_key=settings.bot_instance_id,
        timezone=settings.business_timezone,
        album_settle_seconds=settings.album_settle_seconds,
    )
    await service.initialize(me)

    dispatcher = Dispatcher(storage=MemoryStorage())
    dispatcher.include_router(utility_router)
    dispatcher.include_router(admin_router)
    dispatcher.include_router(group_router)
    worker = ReplyWorker(
        bot,
        service,
        poll_seconds=settings.reply_poll_seconds,
        min_group_interval_seconds=settings.min_group_reply_interval_seconds,
        max_attempts=settings.reply_max_attempts,
    )
    worker.start()
    logger.info(
        "Starting instance=%s bot=@%s timezone=%s",
        settings.bot_instance_id,
        me.username,
        settings.business_timezone,
    )
    try:
        await dispatcher.start_polling(
            bot,
            service=service,
            settings=settings,
            allowed_updates=dispatcher.resolve_used_update_types(),
        )
    finally:
        await worker.stop()
        await bot.session.close()
        await database.dispose()


def run() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    run()
