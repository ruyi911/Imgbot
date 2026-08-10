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
        bot: Bot,
        service: BotService,
        *,
        poll_seconds: float,
        min_group_interval_seconds: float,
        max_attempts: int,
    ) -> None:
        self.bot = bot
        self.service = service
        self.poll_seconds = poll_seconds
        self.min_group_interval_seconds = min_group_interval_seconds
        self.max_attempts = max_attempts
        self._task: asyncio.Task[None] | None = None
        self._stopping = asyncio.Event()
        self._last_send_monotonic: dict[int, float] = {}

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
            await self._respect_group_limit(submission.chat_id)
            try:
                text, keyboard, version = await self.service.reply_payload(submission)
                sent = await self.bot.send_message(
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
                logger.warning(
                    "Telegram rate limit for submission %s, retry in %s seconds",
                    submission.id,
                    exc.retry_after,
                )
                await self.service.mark_reply_failed(
                    submission.id,
                    str(exc),
                    retry_after_seconds=float(exc.retry_after) + 0.2,
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
                self._last_send_monotonic[submission.chat_id] = asyncio.get_running_loop().time()
                await self.service.mark_reply_sent(submission.id, sent.message_id, version)

    async def _respect_group_limit(self, chat_id: int) -> None:
        previous = self._last_send_monotonic.get(chat_id)
        if previous is None:
            return
        elapsed = asyncio.get_running_loop().time() - previous
        remaining = self.min_group_interval_seconds - elapsed
        if remaining > 0:
            await asyncio.sleep(remaining)

