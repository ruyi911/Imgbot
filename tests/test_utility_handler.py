from types import SimpleNamespace

import pytest

from imgbot.handlers.utility import get_id


class FakeMessage:
    def __init__(
        self,
        *,
        user_id: int | None,
        chat_id: int = -100987654321,
        sender_chat_id: int | None = None,
    ) -> None:
        self.message_id = 88
        self.chat = SimpleNamespace(id=chat_id)
        self.from_user = SimpleNamespace(id=user_id) if user_id is not None else None
        self.sender_chat = (
            SimpleNamespace(id=sender_chat_id) if sender_chat_id is not None else None
        )
        self.answers: list[str] = []

    async def answer(self, text: str) -> None:
        self.answers.append(text)


@pytest.mark.asyncio
async def test_getid_returns_user_and_message_ids_without_authorization() -> None:
    message = FakeMessage(user_id=123456789)
    await get_id(message)
    assert "发送者 ID：<code>123456789</code>" in message.answers[0]
    assert "聊天 ID：<code>-100987654321</code>" in message.answers[0]


@pytest.mark.asyncio
async def test_getid_does_not_claim_anonymous_sender_is_a_real_user() -> None:
    message = FakeMessage(
        user_id=1087968824,
        chat_id=-100987654321,
        sender_chat_id=-100123456789,
    )
    await get_id(message)
    assert "发送者 ID：无法获取" in message.answers[0]
    assert "聊天 ID：<code>-100987654321</code>" in message.answers[0]
    assert "-100123456789" not in message.answers[0]
    assert "没有提供真实个人用户 ID" in message.answers[0]
