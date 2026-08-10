from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

router = Router(name="utility")


@router.message(Command("getid"))
async def get_id(message: Message) -> None:
    if message.sender_chat is not None:
        await message.answer(
            "👤 ID 信息\n\n"
            "发送者 ID：无法获取\n"
            f"聊天 ID：<code>{message.chat.id}</code>\n\n"
            "该消息以群组或频道身份发送，未读取到真实用户 ID。"
        )
        return
    if message.from_user is None:
        await message.answer(
            "👤 ID 信息\n\n"
            "发送者 ID：无法获取\n"
            f"聊天 ID：<code>{message.chat.id}</code>\n"
        )
        return
    await message.answer(
        "👤 ID 信息\n\n"
        f"发送者 ID：<code>{message.from_user.id}</code>\n"
        f"聊天 ID：<code>{message.chat.id}</code>\n"
    )
