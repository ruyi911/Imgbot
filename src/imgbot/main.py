from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from imgbot.config import Settings, get_settings
from imgbot.db import Database
from imgbot.filters import BotIdFilter
from imgbot.handlers import (
    admin_router,
    assistant_router,
    group_router,
    utility_router,
)
from imgbot.service import BotService
from imgbot.worker import ReplyWorker

logger = logging.getLogger(__name__)


def build_bots(settings: Settings) -> list[Bot]:
    return [
        Bot(
            token=token,
            session=AiohttpSession(timeout=settings.reply_request_timeout_seconds),
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
        for token in (
            settings.bot_token,
            settings.assistant_bot_token_1,
            settings.assistant_bot_token_2,
        )
    ]


async def main() -> None:
    settings = get_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    database = Database(settings.database_url)
    await database.create_schema()

    bots = build_bots(settings)
    main_bot = bots[0]
    identities = await asyncio.gather(*(bot.get_me() for bot in bots))
    telegram_ids = [identity.id for identity in identities]
    if len(set(telegram_ids)) != 3:
        raise RuntimeError("The three configured tokens must belong to different bots")
    me = identities[0]
    service = BotService(
        database.sessions,
        instance_key=settings.bot_instance_id,
        timezone=settings.business_timezone,
        album_settle_seconds=settings.album_settle_seconds,
    )
    await service.initialize(me)

    dispatcher = Dispatcher(storage=MemoryStorage())
    main_filter = BotIdFilter({me.id})
    utility_router.message.filter(main_filter)
    admin_router.message.filter(main_filter)
    admin_router.callback_query.filter(main_filter)
    group_router.message.filter(main_filter)
    dispatcher.include_router(utility_router)
    dispatcher.include_router(admin_router)
    dispatcher.include_router(group_router)
    assistant_router.message.filter(BotIdFilter(set(telegram_ids[1:])))
    dispatcher.include_router(assistant_router)
    worker = ReplyWorker(
        bots,
        {identity.id: identity.username for identity in identities},
        service,
        poll_seconds=settings.reply_poll_seconds,
        min_group_interval_seconds=settings.min_group_reply_interval_seconds,
        min_combined_interval_seconds=settings.min_combined_reply_interval_seconds,
        max_attempts=settings.reply_max_attempts,
        request_timeout_seconds=settings.reply_request_timeout_seconds,
        sending_lease_seconds=settings.reply_sending_lease_seconds,
    )
    worker.start()
    logger.info(
        "Starting instance=%s main=@%s assistants=%s timezone=%s",
        settings.bot_instance_id,
        me.username,
        ",".join(f"@{identity.username}" for identity in identities[1:]),
        settings.business_timezone,
    )
    try:
        await dispatcher.start_polling(
            *bots,
            service=service,
            settings=settings,
            main_bot=main_bot,
            allowed_updates=dispatcher.resolve_used_update_types(),
        )
    finally:
        await worker.stop()
        await asyncio.gather(*(bot.session.close() for bot in bots))
        await database.dispose()


def run() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    run()
