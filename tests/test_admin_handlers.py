from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from imgbot.handlers.admin import create_export, render_administrator_management


class FakeMessage:
    def __init__(self) -> None:
        self.answers: list[str] = []
        self.answer_options: list[dict] = []
        self.documents: list[object] = []

    async def answer(self, text: str, **kwargs) -> None:
        self.answers.append(text)
        self.answer_options.append(kwargs)

    async def answer_document(self, document, **kwargs) -> None:
        self.documents.append(document)


class FakeCallback:
    def __init__(self, message: FakeMessage) -> None:
        self.from_user = SimpleNamespace(id=42)
        self.data = "exportfmt:csv"
        self.message = message
        self.answered: list[str] = []

    async def answer(self, text: str = "", **kwargs) -> None:
        self.answered.append(text)


class FakeState:
    def __init__(self) -> None:
        self.cleared = False

    async def get_data(self) -> dict[str, str]:
        return {
            "start_utc": datetime(2026, 8, 1, tzinfo=UTC).isoformat(),
            "end_utc": datetime(2026, 8, 2, tzinfo=UTC).isoformat(),
        }

    async def clear(self) -> None:
        self.cleared = True


class FakeService:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.home_rendered = False

    async def export_rows(self, start_utc, end_utc):
        if self.fail:
            raise RuntimeError("test export failure")
        return []

    async def active_binding(self):
        self.home_rendered = True
        return None


def fake_settings() -> SimpleNamespace:
    return SimpleNamespace(
        super_admin_ids=frozenset({42}),
        business_timezone="Asia/Kolkata",
        bot_instance_id="test_instance",
    )


@pytest.mark.asyncio
async def test_export_success_returns_to_home() -> None:
    message = FakeMessage()
    callback = FakeCallback(message)
    state = FakeState()
    service = FakeService()
    await create_export(callback, state, service, fake_settings())
    assert state.cleared is True
    assert service.home_rendered is True
    assert len(message.documents) == 1
    assert any("图片登记机器人管理" in text for text in message.answers)


@pytest.mark.asyncio
async def test_export_failure_reports_error_and_returns_to_home() -> None:
    message = FakeMessage()
    callback = FakeCallback(message)
    state = FakeState()
    service = FakeService(fail=True)
    await create_export(callback, state, service, fake_settings())
    assert state.cleared is True
    assert service.home_rendered is True
    assert any("导出失败" in text for text in message.answers)
    assert any("图片登记机器人管理" in text for text in message.answers)


@pytest.mark.asyncio
async def test_administrator_management_displays_optional_name_and_delete_button() -> None:
    message = FakeMessage()
    service = SimpleNamespace(
        list_admins=lambda: None,
    )

    async def list_admins():
        return [SimpleNamespace(telegram_user_id=123456789, display_name="张三")]

    service.list_admins = list_admins
    await render_administrator_management(message, service, fake_settings())
    assert "• <code>123456789</code>  -  张三" in message.answers[0]
    keyboard = message.answer_options[0]["reply_markup"]
    callbacks = {
        button.callback_data
        for row in keyboard.inline_keyboard
        for button in row
        if button.callback_data
    }
    assert "admins:delete:123456789" in callbacks
