from __future__ import annotations

import asyncio
import logging
from contextlib import suppress

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter
from aiogram.types import ReplyParameters

from imgbot.service import BotService
from imgbot.timeutils import utc_now

logger = logging.getLogger(__name__)


class ReplyWorker:
    def __init__(
        self,
        bots: list[Bot],
        bot_usernames: dict[int, str | None],
        service: BotService,
        *,
        poll_seconds: float,
        min_group_interval_seconds: float,
        min_combined_interval_seconds: float,
        max_attempts: int,
    ) -> None:
        if not bots:
            raise ValueError("ReplyWorker requires at least one bot")
        self.bots = bots
        self.bot_usernames = bot_usernames
        self.service = service
        self.poll_seconds = poll_seconds
        self.min_group_interval_seconds = min_group_interval_seconds
        self.min_combined_interval_seconds = min_combined_interval_seconds
        self.max_attempts = max_attempts
        self._task: asyncio.Task[None] | None = None
        self._stopping = asyncio.Event()
        self._last_bot_send_monotonic: dict[tuple[int, int], float] = {}
        self._last_combined_send_monotonic: dict[int, float] = {}
        self._bot_retry_not_before: dict[int, float] = {}
        self._next_bot_index = 0

    def start(self) -> None:
        if self._task is not None:
            raise RuntimeError("ReplyWorker is already started")
        self._task = asyncio.create_task(self.run(), name="reply-worker")

    async def stop(self) -> None:
        self._stopping.set()
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def run(self) -> None:
        while not self._stopping.is_set():
            submission = await self.service.next_pending_reply(utc_now())
            if submission is None:
                await asyncio.sleep(self.poll_seconds)
                continue
            bot = self._next_bot()
            await self._respect_group_limit(submission.chat_id, bot.id)
            try:
                text, keyboard, version = await self.service.reply_payload(submission)
                sent = await bot.send_message(
                    chat_id=submission.chat_id,
                    text=text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=keyboard,
                    reply_parameters=ReplyParameters(
                        message_id=submission.primary_message_id,
                        allow_sending_without_reply=True,
                    ),
                )
            except TelegramRetryAfter as exc:
                self._bot_retry_not_before[bot.id] = (
                    asyncio.get_running_loop().time() + float(exc.retry_after) + 0.2
                )
                logger.warning(
                    "Telegram rate limit bot_id=%s submission=%s, retry in %s seconds",
                    bot.id,
                    submission.id,
                    exc.retry_after,
                )
                await self.service.mark_reply_failed(
                    submission.id,
                    str(exc),
                    retry_after_seconds=self.poll_seconds,
                    max_attempts=self.max_attempts,
                )
            except TelegramAPIError as exc:
                logger.exception("Telegram reply failed for submission %s", submission.id)
                await self.service.mark_reply_failed(
                    submission.id,
                    str(exc),
                    retry_after_seconds=None,
                    max_attempts=self.max_attempts,
                )
            except Exception as exc:
                logger.exception("Unexpected reply failure for submission %s", submission.id)
                await self.service.mark_reply_failed(
                    submission.id,
                    str(exc),
                    retry_after_seconds=None,
                    max_attempts=self.max_attempts,
                )
            else:
                sent_at = asyncio.get_running_loop().time()
                self._last_bot_send_monotonic[(bot.id, submission.chat_id)] = sent_at
                self._last_combined_send_monotonic[submission.chat_id] = sent_at
                await self.service.mark_reply_sent(
                    submission.id,
                    sent.message_id,
                    version,
                    bot_telegram_id=bot.id,
                    bot_username=self.bot_usernames.get(bot.id),
                )

    def _next_bot(self) -> Bot:
        now = asyncio.get_running_loop().time()
        for offset in range(len(self.bots)):
            index = (self._next_bot_index + offset) % len(self.bots)
            bot = self.bots[index]
            if self._bot_retry_not_before.get(bot.id, 0) <= now:
                self._next_bot_index = (index + 1) % len(self.bots)
                return bot
        bot = min(
            self.bots,
            key=lambda item: self._bot_retry_not_before.get(item.id, 0),
        )
        self._next_bot_index = (self.bots.index(bot) + 1) % len(self.bots)
        return bot

    async def _respect_group_limit(self, chat_id: int, bot_id: int) -> None:
        now = asyncio.get_running_loop().time()
        bot_previous = self._last_bot_send_monotonic.get((bot_id, chat_id))
        combined_previous = self._last_combined_send_monotonic.get(chat_id)
        remaining = 0.0
        remaining = max(
            remaining, self._bot_retry_not_before.get(bot_id, 0) - now
        )
        if bot_previous is not None:
            remaining = max(
                remaining, self.min_group_interval_seconds - (now - bot_previous)
            )
        if combined_previous is not None:
            remaining = max(
                remaining, self.min_combined_interval_seconds - (now - combined_previous)
            )
        if remaining > 0:
            await asyncio.sleep(remaining)
