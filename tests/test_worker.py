import asyncio
from types import SimpleNamespace

from imgbot.worker import ReplyWorker


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
