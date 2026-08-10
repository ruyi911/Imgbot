from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from imgbot.db import Database
from imgbot.service import BotService, PendingBinding


@pytest.fixture
async def service() -> BotService:
    database = Database("sqlite+aiosqlite:///:memory:")
    await database.create_schema()
    result = BotService(
        database.sessions,
        instance_key="test_instance",
        timezone="Asia/Kolkata",
        album_settle_seconds=1.5,
    )
    await result.initialize(SimpleNamespace(id=999, username="photo_test_bot"))
    await result.bind_group(
        PendingBinding(chat_id=-100123, chat_title="测试群", chat_type="supergroup"),
        actor_user_id=42,
    )
    yield result
    await database.dispose()


def make_message(message_id: int, media_group_id: str | None = None) -> SimpleNamespace:
    user = SimpleNamespace(
        id=12345,
        full_name="=测试用户",
        first_name="=测试",
        last_name="用户",
        username="tester",
    )
    return SimpleNamespace(
        message_id=message_id,
        media_group_id=media_group_id,
        date=datetime(2026, 8, 3, 6, 30, tzinfo=UTC),
        chat=SimpleNamespace(id=-100123),
        from_user=user,
        sender_chat=None,
    )


@pytest.mark.asyncio
async def test_album_is_one_submission_and_duplicate_part_is_idempotent(
    service: BotService,
) -> None:
    first = await service.record_photo(make_message(10, "album-1"))
    second = await service.record_photo(make_message(11, "album-1"))
    duplicate = await service.record_photo(make_message(11, "album-1"))

    assert first.created is True
    assert second.created is False
    assert duplicate.created is False
    rows = await service.export_rows(
        datetime(2026, 8, 3, 0, 0, tzinfo=UTC),
        datetime(2026, 8, 4, 0, 0, tzinfo=UTC),
    )
    assert len(rows) == 1
    assert rows[0].photo_count == 2
    assert rows[0].primary_message_id == 10


@pytest.mark.asyncio
async def test_each_single_photo_is_retained(service: BotService) -> None:
    await service.record_photo(make_message(20))
    await service.record_photo(make_message(21))
    rows = await service.export_rows(
        datetime(2026, 8, 3, 0, 0, tzinfo=UTC),
        datetime(2026, 8, 4, 0, 0, tzinfo=UTC),
    )
    assert len(rows) == 2


@pytest.mark.asyncio
async def test_messages_from_unbound_group_are_ignored(service: BotService) -> None:
    message = make_message(30)
    message.chat.id = -100999
    result = await service.record_photo(message)
    assert result.accepted is False


@pytest.mark.asyncio
async def test_unbind_stops_new_records_and_cancels_pending_replies(service: BotService) -> None:
    await service.record_photo(make_message(40))
    assert await service.unbind_group(actor_user_id=42) is True
    result = await service.record_photo(make_message(41))
    assert result.accepted is False
    assert await service.next_pending_reply(datetime.now(UTC)) is None


@pytest.mark.asyncio
async def test_super_admin_can_add_regular_admin_once(service: BotService) -> None:
    assert await service.is_admin(555) is False
    assert await service.add_admin(555, "张三", actor_user_id=42) is True
    assert await service.add_admin(555, "重复名称", actor_user_id=42) is False
    assert await service.is_admin(555) is True
    administrators = await service.list_admins()
    assert [item.telegram_user_id for item in administrators] == [555]
    assert administrators[0].display_name == "张三"


@pytest.mark.asyncio
async def test_super_admin_can_remove_and_readd_regular_admin(service: BotService) -> None:
    assert await service.add_admin(556, None, actor_user_id=42) is True
    assert await service.remove_admin(556, actor_user_id=42) is True
    assert await service.remove_admin(556, actor_user_id=42) is False
    assert await service.is_admin(556) is False
    assert await service.add_admin(556, "李四", actor_user_id=42) is True
    administrators = await service.list_admins()
    assert [(item.telegram_user_id, item.display_name) for item in administrators] == [
        (556, "李四")
    ]
