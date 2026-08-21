import asyncio
from types import SimpleNamespace

from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramEntityTooLarge,
    TelegramNetworkError,
    TelegramRetryAfter,
)
from aiogram.methods import SendMessage

from imgbot.models import ReplyStatus
from imgbot.worker import ReplyWorker


class FailingBot:
    def __init__(self, exception: Exception) -> None:
        self.id = 100
        self.exception = exception
        self.send_options: dict[str, object] = {}

    async def send_message(self, **kwargs):
        self.send_options = kwargs
        raise self.exception


class OneSubmissionService:
    def __init__(self) -> None:
        self.submission = SimpleNamespace(
            id=7,
            chat_id=-100123,
            primary_message_id=55,
            reply_attempts=1,
        )
        self.failure_options: dict[str, object] = {}

    async def next_pending_reply(self, now, *, sending_lease_seconds):
        return self.submission

    async def reply_payload(self, submission):
        return "reply", None, 1

    async def mark_reply_failed(self, submission_id, error, **kwargs):
        self.failure_options = kwargs
        return ReplyStatus.FAILED if kwargs.get("retryable") is False else ReplyStatus.RETRYING


async def test_reply_worker_rotates_three_bots_in_order() -> None:
    bots = [SimpleNamespace(id=bot_id) for bot_id in (100, 200, 300)]
    worker = ReplyWorker(
        bots,
        {100: "main", 200: "assistant_one", 300: "assistant_two"},
        SimpleNamespace(),
        poll_seconds=0.5,
        min_group_interval_seconds=3.1,
        min_combined_interval_seconds=1.05,
        max_attempts=5,
    )

    assert [worker._next_bot().id for _ in range(7)] == [
        100,
        200,
        300,
        100,
        200,
        300,
        100,
    ]


async def test_reply_worker_skips_bot_during_telegram_retry_after() -> None:
    bots = [SimpleNamespace(id=bot_id) for bot_id in (100, 200, 300)]
    worker = ReplyWorker(
        bots,
        {100: "main", 200: "assistant_one", 300: "assistant_two"},
        SimpleNamespace(),
        poll_seconds=0.5,
        min_group_interval_seconds=3.1,
        min_combined_interval_seconds=1.05,
        max_attempts=5,
    )
    worker._bot_retry_not_before[100] = asyncio.get_running_loop().time() + 30

    assert [worker._next_bot().id for _ in range(4)] == [200, 300, 200, 300]


async def test_network_error_uses_bounded_backoff_without_sleeping_worker(
    monkeypatch,
) -> None:
    method = SendMessage(chat_id=-100123, text="reply")
    bot = FailingBot(TelegramNetworkError(method=method, message="timeout"))
    service = OneSubmissionService()
    sleep_calls: list[float] = []

    async def record_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    monkeypatch.setattr("imgbot.worker.asyncio.sleep", record_sleep)
    worker = ReplyWorker(
        [bot],
        {100: "main"},
        service,
        poll_seconds=0.5,
        min_group_interval_seconds=3.1,
        min_combined_interval_seconds=1.05,
        max_attempts=5,
        request_timeout_seconds=12,
        sending_lease_seconds=90,
    )
    await worker._run_once()

    assert bot.send_options["request_timeout"] == 12
    assert service.failure_options["error_type"] == "TELEGRAM_NETWORK_UNCERTAIN"
    assert service.failure_options["retry_after_seconds"] == 1.0
    assert service.failure_options["expected_attempt"] == 1
    assert sleep_calls == []


def test_network_backoff_is_exactly_one_then_two_seconds() -> None:
    assert [ReplyWorker._network_retry_delay(attempt) for attempt in range(1, 5)] == [
        1.0,
        2.0,
        2.0,
        2.0,
    ]


async def test_retry_after_cools_only_current_bot_and_requeues_submission() -> None:
    method = SendMessage(chat_id=-100123, text="reply")
    limited_bot = FailingBot(
        TelegramRetryAfter(method=method, message="flood control", retry_after=7)
    )
    other_bots = [SimpleNamespace(id=200), SimpleNamespace(id=300)]
    service = OneSubmissionService()
    worker = ReplyWorker(
        [limited_bot, *other_bots],
        {100: "main", 200: "assistant_one", 300: "assistant_two"},
        service,
        poll_seconds=0.5,
        min_group_interval_seconds=3.1,
        min_combined_interval_seconds=1.05,
        max_attempts=5,
    )
    before = asyncio.get_running_loop().time()

    await worker._run_once()

    assert worker._bot_retry_not_before[100] >= before + 7
    assert worker._next_bot().id == 200
    assert service.failure_options["error_type"] == "TELEGRAM_RETRY_AFTER"
    assert service.failure_options["retry_after_seconds"] == 0.5


async def test_permanent_telegram_error_is_not_retried() -> None:
    method = SendMessage(chat_id=-100123, text="reply")
    bot = FailingBot(TelegramBadRequest(method=method, message="bad chat"))
    service = OneSubmissionService()
    worker = ReplyWorker(
        [bot],
        {100: "main"},
        service,
        poll_seconds=0.5,
        min_group_interval_seconds=3.1,
        min_combined_interval_seconds=1.05,
        max_attempts=5,
    )

    await worker._run_once()

    assert service.failure_options["retryable"] is False
    assert service.failure_options["error_type"] == "TelegramBadRequest"


async def test_entity_too_large_is_not_misclassified_as_network_error() -> None:
    method = SendMessage(chat_id=-100123, text="reply")
    bot = FailingBot(TelegramEntityTooLarge(method=method, message="too large"))
    service = OneSubmissionService()
    worker = ReplyWorker(
        [bot],
        {100: "main"},
        service,
        poll_seconds=0.5,
        min_group_interval_seconds=3.1,
        min_combined_interval_seconds=1.05,
        max_attempts=5,
    )

    await worker._run_once()

    assert service.failure_options["retryable"] is False
    assert service.failure_options["error_type"] == "TelegramEntityTooLarge"


async def test_worker_continues_after_unexpected_queue_error() -> None:
    class FlakyService:
        def __init__(self) -> None:
            self.calls = 0

        async def next_pending_reply(self, now, *, sending_lease_seconds):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("temporary database failure")
            return None

    service = FlakyService()
    worker = ReplyWorker(
        [SimpleNamespace(id=100)],
        {100: "main"},
        service,
        poll_seconds=0.01,
        min_group_interval_seconds=3.1,
        min_combined_interval_seconds=1.05,
        max_attempts=5,
    )

    worker.start()
    await asyncio.sleep(0.05)
    await worker.stop()

    assert service.calls >= 2
