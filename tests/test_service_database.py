from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from imgbot.db import Database
from imgbot.models import ReplyStatus, Submission
from imgbot.service import BotService, PendingBinding
from imgbot.timeutils import ensure_utc


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


@pytest.mark.asyncio
async def test_start_page_content_is_saved_separately_from_group_reply(service: BotService) -> None:
    start_page = await service.get_start_page()
    assert start_page.text == "欢迎使用本机器人。"
    assert start_page.photo_file_id is None

    await service.update_start_page_text("<b>欢迎</b>", actor_user_id=42)
    await service.update_start_page_photo("photo-file-id", actor_user_id=42)
    rows = service.parse_button_definition("1|1|官方群|https://t.me/example")
    await service.replace_start_page_buttons(rows, actor_user_id=42)

    text, photo_file_id, keyboard = await service.start_page_payload()
    assert text == "<b>欢迎</b>"
    assert photo_file_id == "photo-file-id"
    assert keyboard is not None
    assert keyboard.inline_keyboard[0][0].text == "官方群"
    assert keyboard.inline_keyboard[0][0].url == "https://t.me/example"


@pytest.mark.asyncio
async def test_assistant_start_photo_cache_is_scoped_to_source_photo(
    service: BotService,
) -> None:
    assert await service.get_start_page_photo_cache(2001, "source-a") is None
    await service.set_start_page_photo_cache(2001, "source-a", "assistant-a")
    assert await service.get_start_page_photo_cache(2001, "source-a") == "assistant-a"
    assert await service.get_start_page_photo_cache(2001, "source-b") is None

    await service.set_start_page_photo_cache(2001, "source-b", "assistant-b")
    assert await service.get_start_page_photo_cache(2001, "source-a") is None
    assert await service.get_start_page_photo_cache(2001, "source-b") == "assistant-b"


@pytest.mark.asyncio
async def test_sent_reply_records_which_bot_sent_it(service: BotService) -> None:
    await service.record_photo(make_message(50))
    pending = await service.next_pending_reply(datetime.now(UTC))
    assert pending is not None
    await service.mark_reply_sent(
        pending.id,
        9001,
        3,
        bot_telegram_id=2002,
        bot_username="assistant_two",
        expected_attempt=pending.reply_attempts,
    )
    rows = await service.export_rows(
        datetime(2026, 8, 3, 0, 0, tzinfo=UTC),
        datetime(2026, 8, 4, 0, 0, tzinfo=UTC),
    )
    assert rows[0].reply_bot_telegram_id == 2002
    assert rows[0].reply_bot_username == "assistant_two"


@pytest.mark.asyncio
async def test_network_failure_retries_twice_then_becomes_failed(
    service: BotService, monkeypatch
) -> None:
    await service.record_photo(make_message(60))
    future = datetime.now(UTC) + timedelta(days=1)
    failure_time = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
    monkeypatch.setattr("imgbot.service.utc_now", lambda: failure_time)

    for expected_attempt in range(1, 4):
        submission = await service.next_pending_reply(
            future, sending_lease_seconds=90
        )
        assert submission is not None
        assert submission.reply_attempts == expected_attempt
        if expected_attempt > 1:
            assert submission.reply_error == "network unavailable"
            assert submission.reply_error_type == "TELEGRAM_NETWORK"
        status = await service.mark_reply_failed(
            submission.id,
            "network unavailable",
            error_type="TELEGRAM_NETWORK",
            retry_after_seconds=None,
            max_attempts=3,
            expected_attempt=expected_attempt,
        )
        expected_status = (
            ReplyStatus.RETRYING if expected_attempt < 3 else ReplyStatus.FAILED
        )
        assert status == expected_status
        rows = await service.export_rows(
            datetime(2026, 8, 3, 0, 0, tzinfo=UTC),
            datetime(2026, 8, 4, 0, 0, tzinfo=UTC),
        )
        expected_retry_at = (
            failure_time + timedelta(seconds=2 ** (expected_attempt - 1))
            if expected_attempt < 3
            else None
        )
        actual_retry_at = rows[0].next_retry_at
        assert (
            ensure_utc(actual_retry_at) if actual_retry_at is not None else None
        ) == expected_retry_at

    rows = await service.export_rows(
        datetime(2026, 8, 3, 0, 0, tzinfo=UTC),
        datetime(2026, 8, 4, 0, 0, tzinfo=UTC),
    )
    assert rows[0].reply_status == ReplyStatus.FAILED
    assert rows[0].reply_attempts == 3
    assert rows[0].reply_error_type == "TELEGRAM_NETWORK"
    assert rows[0].next_retry_at is None
    assert rows[0].sending_started_at is None


@pytest.mark.asyncio
async def test_new_pending_reply_is_claimed_before_due_retry(
    service: BotService, monkeypatch
) -> None:
    first = await service.record_photo(make_message(62))
    claim_time = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
    retrying = await service.next_pending_reply(
        claim_time, sending_lease_seconds=90
    )
    assert retrying is not None
    assert retrying.id == first.submission_id

    monkeypatch.setattr("imgbot.service.utc_now", lambda: claim_time)
    status = await service.mark_reply_failed(
        retrying.id,
        "temporary network failure",
        error_type="TELEGRAM_NETWORK",
        retry_after_seconds=1,
        max_attempts=3,
        expected_attempt=retrying.reply_attempts,
    )
    assert status == ReplyStatus.RETRYING

    second = await service.record_photo(make_message(63))
    pending = await service.next_pending_reply(
        claim_time + timedelta(seconds=2), sending_lease_seconds=90
    )

    assert pending is not None
    assert pending.id == second.submission_id


@pytest.mark.asyncio
async def test_expired_sending_lease_is_reclaimed_and_stale_writer_is_rejected(
    service: BotService,
) -> None:
    await service.record_photo(make_message(61))
    now = datetime.now(UTC)
    first_claim = await service.next_pending_reply(now, sending_lease_seconds=90)
    assert first_claim is not None

    async with service.sessions.begin() as session:
        stored = await session.get(Submission, first_claim.id)
        assert stored is not None
        stored.sending_started_at = now - timedelta(seconds=120)

    second_claim = await service.next_pending_reply(now, sending_lease_seconds=90)
    assert second_claim is not None
    assert second_claim.id == first_claim.id
    assert second_claim.reply_attempts == 2

    stale_update = await service.mark_reply_sent(
        first_claim.id,
        9100,
        1,
        bot_telegram_id=2001,
        bot_username="stale_bot",
        expected_attempt=1,
    )
    assert stale_update is False

    current_update = await service.mark_reply_sent(
        second_claim.id,
        9101,
        1,
        bot_telegram_id=2002,
        bot_username="current_bot",
        expected_attempt=2,
    )
    assert current_update is True
