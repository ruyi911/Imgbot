from __future__ import annotations

import io
import logging

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import CommandStart
from aiogram.types import BufferedInputFile, Message

from imgbot.service import BotService

logger = logging.getLogger(__name__)
router = Router(name="assistant")
router.message.filter(F.chat.type == ChatType.PRIVATE)


@router.message(CommandStart())
async def assistant_start(
    message: Message,
    bot: Bot,
    main_bot: Bot,
    service: BotService,
) -> None:
    text, source_photo_file_id, keyboard = await service.start_page_payload()
    if source_photo_file_id is None:
        await message.answer(text, reply_markup=keyboard)
        return

    cached_file_id = await service.get_start_page_photo_cache(
        bot.id, source_photo_file_id
    )
    if cached_file_id is not None:
        try:
            await message.answer_photo(
                photo=cached_file_id,
                caption=text,
                reply_markup=keyboard,
            )
            return
        except TelegramAPIError:
            logger.warning(
                "Cached assistant start photo failed bot_id=%s; refreshing",
                bot.id,
                exc_info=True,
            )

    try:
        destination = io.BytesIO()
        await main_bot.download(source_photo_file_id, destination=destination)
        sent = await message.answer_photo(
            photo=BufferedInputFile(
                destination.getvalue(), filename="start-page-photo.jpg"
            ),
            caption=text,
            reply_markup=keyboard,
        )
        if sent.photo:
            await service.set_start_page_photo_cache(
                bot.id,
                source_photo_file_id,
                sent.photo[-1].file_id,
            )
    except (TelegramAPIError, OSError):
        logger.exception("Assistant start photo sync failed bot_id=%s", bot.id)
        await message.answer(text, reply_markup=keyboard)
