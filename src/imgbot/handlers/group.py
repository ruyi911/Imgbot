from __future__ import annotations

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.types import Message

from imgbot.service import BotService

router = Router(name="group")
router.message.filter(F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}))


@router.message(F.photo)
async def record_group_photo(message: Message, service: BotService) -> None:
    await service.record_photo(message)

