import io
from types import SimpleNamespace

import pytest
from aiogram.types import BufferedInputFile

from imgbot.handlers.assistant import assistant_start


class FakeMessage:
    def __init__(self) -> None:
        self.answers: list[tuple[str, dict]] = []
        self.photos: list[tuple[object, dict]] = []

    async def answer(self, text: str, **kwargs):
        self.answers.append((text, kwargs))

    async def answer_photo(self, photo: object, **kwargs):
        self.photos.append((photo, kwargs))
        return SimpleNamespace(photo=[SimpleNamespace(file_id="assistant-file-id")])


class FakeService:
    def __init__(self, source_photo: str | None, cached_photo: str | None = None) -> None:
        self.source_photo = source_photo
        self.cached_photo = cached_photo
        self.saved_cache: tuple[int, str, str] | None = None

    async def start_page_payload(self):
        return "<b>同步首页</b>", self.source_photo, None

    async def get_start_page_photo_cache(self, bot_id: int, source: str):
        return self.cached_photo

    async def set_start_page_photo_cache(
        self, bot_id: int, source: str, cached: str
    ) -> None:
        self.saved_cache = (bot_id, source, cached)


class FakeMainBot:
    def __init__(self) -> None:
        self.downloaded: list[str] = []

    async def download(self, file_id: str, destination: io.BytesIO) -> None:
        self.downloaded.append(file_id)
        destination.write(b"photo-bytes")


@pytest.mark.asyncio
async def test_assistant_start_uses_shared_text_without_admin_panel() -> None:
    message = FakeMessage()
    service = FakeService(None)

    await assistant_start(
        message,
        SimpleNamespace(id=2001),
        FakeMainBot(),
        service,
    )

    assert message.answers == [("<b>同步首页</b>", {"reply_markup": None})]
    assert message.photos == []


@pytest.mark.asyncio
async def test_assistant_start_reuses_its_cached_photo() -> None:
    message = FakeMessage()
    main_bot = FakeMainBot()
    service = FakeService("main-file-id", "assistant-cached-id")

    await assistant_start(
        message,
        SimpleNamespace(id=2001),
        main_bot,
        service,
    )

    assert main_bot.downloaded == []
    assert message.photos[0][0] == "assistant-cached-id"


@pytest.mark.asyncio
async def test_assistant_start_transfers_and_caches_new_main_photo() -> None:
    message = FakeMessage()
    main_bot = FakeMainBot()
    service = FakeService("main-file-id")

    await assistant_start(
        message,
        SimpleNamespace(id=2001),
        main_bot,
        service,
    )

    assert main_bot.downloaded == ["main-file-id"]
    assert isinstance(message.photos[0][0], BufferedInputFile)
    assert service.saved_cache == (2001, "main-file-id", "assistant-file-id")
