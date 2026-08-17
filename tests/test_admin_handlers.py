from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from imgbot.handlers.admin import (
    begin_start_page_media,
    create_export,
    render_administrator_management,
    start,
)


class FakeMessage:
    def __init__(self) -> None:
        self.answers: list[str] = []
        self.answer_options: list[dict] = []
        self.documents: list[object] = []
        self.photos: list[tuple[str, dict]] = []

    async def answer(self, text: str, **kwargs) -> None:
        self.answers.append(text)
        self.answer_options.append(kwargs)

    async def answer_document(self, document, **kwargs) -> None:
        self.documents.append(document)

    async def answer_photo(self, photo: str, **kwargs) -> None:
        self.photos.append((photo, kwargs))


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


class EmptyState:
    def __init__(self) -> None:
        self.cleared = False

    async def clear(self) -> None:
        self.cleared = True


class StateRecorder(EmptyState):
    def __init__(self) -> None:
        super().__init__()
        self.current_state = None

    async def set_state(self, state) -> None:
        self.current_state = state


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


class StartPageService:
    async def start_page_payload(self):
        return "<b>欢迎</b>", "start-photo", None

    async def active_binding(self):
        return None

    async def is_admin(self, user_id: int) -> bool:
        return False


@pytest.mark.asyncio
async def test_start_sends_public_page_to_every_private_user() -> None:
    message = FakeMessage()
    message.from_user = SimpleNamespace(id=123)
    state = EmptyState()

    await start(message, state, StartPageService(), fake_settings())

    assert state.cleared is True
    assert message.photos == [
        ("start-photo", {"caption": "<b>欢迎</b>", "reply_markup": None})
    ]
    assert message.answers == []


@pytest.mark.asyncio
async def test_start_sends_admin_panel_after_public_page_for_administrator() -> None:
    message = FakeMessage()
    message.from_user = SimpleNamespace(id=42)
    state = EmptyState()

    await start(message, state, StartPageService(), fake_settings())

    assert message.photos == [
        ("start-photo", {"caption": "<b>欢迎</b>", "reply_markup": None})
    ]
    assert "图片登记机器人管理" in message.answers[0]
    keyboard = message.answer_options[0]["reply_markup"]
    callbacks = {
        button.callback_data
        for row in keyboard.inline_keyboard
        for button in row
        if button.callback_data
    }
    assert {"admin:start_media", "admin:start_text", "admin:start_buttons"} <= callbacks


class TextOnlyStartPageService(StartPageService):
    async def start_page_payload(self):
        return "<b>欢迎</b>", None, None


@pytest.mark.asyncio
async def test_start_without_photo_sends_one_text_message() -> None:
    message = FakeMessage()
    message.from_user = SimpleNamespace(id=123)

    await start(message, EmptyState(), TextOnlyStartPageService(), fake_settings())

    assert message.photos == []
    assert message.answers == ["<b>欢迎</b>"]


@pytest.mark.asyncio
async def test_start_page_media_editor_previews_current_photo_before_prompt() -> None:
    message = FakeMessage()
    callback = FakeCallback(message)
    state = StateRecorder()
    service = SimpleNamespace(
        get_start_page=lambda: None,
    )

    async def get_start_page():
        return SimpleNamespace(photo_file_id="current-photo")

    service.get_start_page = get_start_page
    await begin_start_page_media(callback, state, service, fake_settings())

    assert message.photos == [("current-photo", {})]
    assert "首页媒体" in message.answers[0]
