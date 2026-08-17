from __future__ import annotations

import asyncio
import html
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from string import Formatter
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from imgbot.models import (
    Administrator,
    AuditLog,
    BindingStatus,
    BotInstance,
    GroupBinding,
    ReplyStatus,
    ReplyTemplate,
    StartPage,
    StartPageButton,
    Submission,
    SubmissionPart,
    TemplateButton,
)
from imgbot.timeutils import ensure_utc, utc_now

logger = logging.getLogger(__name__)

DEFAULT_TEMPLATE = (
    "📌 已记录 <code>{tg_id}</code> | <b>{display_name}</b>\n"
    "您的信息已登记，发送时间：{send_time}"
)
DEFAULT_START_PAGE_TEXT = "欢迎使用本机器人。"
ALLOWED_TEMPLATE_FIELDS = {
    "tg_id",
    "display_name",
    "username",
    "send_time",
    "group_name",
    "message_id",
}
HTTP_HOST_LABEL = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")


@dataclass(frozen=True)
class InstanceIdentity:
    id: int
    instance_key: str
    bot_telegram_id: int
    bot_username: str | None
    timezone: str


@dataclass(frozen=True)
class PendingBinding:
    chat_id: int
    chat_title: str
    chat_type: str


@dataclass(frozen=True)
class RecordResult:
    accepted: bool
    created: bool = False
    submission_id: int | None = None


class BotService:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        instance_key: str,
        timezone: str,
        album_settle_seconds: float,
    ) -> None:
        self.sessions = sessions
        self.instance_key = instance_key
        self.timezone = timezone
        self.album_settle_seconds = album_settle_seconds
        self.identity: InstanceIdentity | None = None
        self._record_lock = asyncio.Lock()

    @property
    def instance_id(self) -> int:
        if self.identity is None:
            raise RuntimeError("BotService has not been initialized")
        return self.identity.id

    async def initialize(self, bot_user: Any) -> InstanceIdentity:
        now = utc_now()
        async with self.sessions.begin() as session:
            instance = await session.scalar(
                select(BotInstance).where(BotInstance.instance_key == self.instance_key)
            )
            if instance is None:
                instance = BotInstance(
                    instance_key=self.instance_key,
                    bot_telegram_id=bot_user.id,
                    bot_username=bot_user.username,
                    timezone=self.timezone,
                    created_at=now,
                )
                session.add(instance)
                await session.flush()
            else:
                if instance.bot_telegram_id != bot_user.id:
                    raise RuntimeError(
                        "BOT_INSTANCE_ID is already owned by a different Telegram bot"
                    )
                instance.bot_username = bot_user.username
                instance.timezone = self.timezone

            template = await session.scalar(
                select(ReplyTemplate).where(ReplyTemplate.bot_instance_id == instance.id)
            )
            if template is None:
                session.add(
                    ReplyTemplate(
                        bot_instance_id=instance.id,
                        text=DEFAULT_TEMPLATE,
                        version=1,
                        updated_at=now,
                    )
                )
            start_page = await session.scalar(
                select(StartPage).where(StartPage.bot_instance_id == instance.id)
            )
            if start_page is None:
                session.add(
                    StartPage(
                        bot_instance_id=instance.id,
                        text=DEFAULT_START_PAGE_TEXT,
                        updated_at=now,
                    )
                )
            await session.execute(
                update(Submission)
                .where(
                    Submission.bot_instance_id == instance.id,
                    Submission.reply_status == ReplyStatus.SENDING,
                )
                .values(reply_status=ReplyStatus.RETRYING, next_retry_at=now)
            )
            self.identity = InstanceIdentity(
                id=instance.id,
                instance_key=instance.instance_key,
                bot_telegram_id=instance.bot_telegram_id,
                bot_username=instance.bot_username,
                timezone=instance.timezone,
            )
        return self.identity

    async def active_binding(self) -> GroupBinding | None:
        async with self.sessions() as session:
            return await session.scalar(
                select(GroupBinding).where(
                    GroupBinding.bot_instance_id == self.instance_id,
                    GroupBinding.status == BindingStatus.ACTIVE,
                )
            )

    async def is_admin(self, telegram_user_id: int) -> bool:
        async with self.sessions() as session:
            administrator = await session.scalar(
                select(Administrator).where(
                    Administrator.bot_instance_id == self.instance_id,
                    Administrator.telegram_user_id == telegram_user_id,
                    Administrator.enabled.is_(True),
                )
            )
            return administrator is not None

    async def list_admins(self) -> list[Administrator]:
        async with self.sessions() as session:
            result = await session.scalars(
                select(Administrator)
                .where(
                    Administrator.bot_instance_id == self.instance_id,
                    Administrator.enabled.is_(True),
                )
                .order_by(Administrator.added_at, Administrator.telegram_user_id)
            )
            return list(result)

    async def add_admin(
        self,
        telegram_user_id: int,
        display_name: str | None,
        actor_user_id: int,
    ) -> bool:
        if telegram_user_id <= 0:
            raise ValueError("管理员 TG ID 必须是正整数")
        normalized_name = display_name.strip() if display_name else None
        if normalized_name and len(normalized_name) > 100:
            raise ValueError("管理员名称不能超过 100 个字符")
        now = utc_now()
        async with self.sessions.begin() as session:
            administrator = await session.scalar(
                select(Administrator).where(
                    Administrator.bot_instance_id == self.instance_id,
                    Administrator.telegram_user_id == telegram_user_id,
                )
            )
            if administrator is not None and administrator.enabled:
                return False
            if administrator is None:
                administrator = Administrator(
                    bot_instance_id=self.instance_id,
                    telegram_user_id=telegram_user_id,
                    display_name=normalized_name,
                    enabled=True,
                    added_by=actor_user_id,
                    added_at=now,
                )
                session.add(administrator)
            else:
                administrator.enabled = True
                administrator.display_name = normalized_name
                administrator.added_by = actor_user_id
                administrator.added_at = now
            session.add(
                AuditLog(
                    bot_instance_id=self.instance_id,
                    actor_user_id=actor_user_id,
                    action="ADMIN_ADDED",
                    details=json.dumps(
                        {
                            "telegram_user_id": telegram_user_id,
                            "display_name": normalized_name,
                        },
                        ensure_ascii=False,
                    ),
                    created_at=now,
                )
            )
            return True

    async def remove_admin(self, telegram_user_id: int, actor_user_id: int) -> bool:
        now = utc_now()
        async with self.sessions.begin() as session:
            administrator = await session.scalar(
                select(Administrator).where(
                    Administrator.bot_instance_id == self.instance_id,
                    Administrator.telegram_user_id == telegram_user_id,
                    Administrator.enabled.is_(True),
                )
            )
            if administrator is None:
                return False
            administrator.enabled = False
            session.add(
                AuditLog(
                    bot_instance_id=self.instance_id,
                    actor_user_id=actor_user_id,
                    action="ADMIN_REMOVED",
                    details=json.dumps(
                        {
                            "telegram_user_id": administrator.telegram_user_id,
                            "display_name": administrator.display_name,
                        },
                        ensure_ascii=False,
                    ),
                    created_at=now,
                )
            )
            return True

    async def bind_group(self, pending: PendingBinding, actor_user_id: int) -> GroupBinding:
        now = utc_now()
        async with self.sessions.begin() as session:
            current = await session.scalar(
                select(GroupBinding).where(
                    GroupBinding.bot_instance_id == self.instance_id,
                    GroupBinding.status == BindingStatus.ACTIVE,
                )
            )
            if current is not None:
                raise ValueError("当前机器人已经绑定群组，请先解除原绑定")
            binding = GroupBinding(
                bot_instance_id=self.instance_id,
                chat_id=pending.chat_id,
                chat_title=pending.chat_title,
                chat_type=pending.chat_type,
                status=BindingStatus.ACTIVE,
                bound_by=actor_user_id,
                bound_at=now,
            )
            session.add(binding)
            session.add(
                AuditLog(
                    bot_instance_id=self.instance_id,
                    actor_user_id=actor_user_id,
                    action="GROUP_BOUND",
                    details=json.dumps(
                        {"chat_id": pending.chat_id, "chat_title": pending.chat_title},
                        ensure_ascii=False,
                    ),
                    created_at=now,
                )
            )
            await session.flush()
            return binding

    async def unbind_group(self, actor_user_id: int) -> bool:
        now = utc_now()
        async with self.sessions.begin() as session:
            binding = await session.scalar(
                select(GroupBinding).where(
                    GroupBinding.bot_instance_id == self.instance_id,
                    GroupBinding.status == BindingStatus.ACTIVE,
                )
            )
            if binding is None:
                return False
            binding.status = BindingStatus.UNBOUND
            binding.unbound_by = actor_user_id
            binding.unbound_at = now
            await session.execute(
                update(Submission)
                .where(
                    Submission.group_binding_id == binding.id,
                    Submission.reply_status.in_([ReplyStatus.PENDING, ReplyStatus.RETRYING]),
                )
                .values(
                    reply_status=ReplyStatus.CANCELLED,
                    next_retry_at=None,
                    reply_error="群组已解除绑定，取消待发送回复",
                )
            )
            session.add(
                AuditLog(
                    bot_instance_id=self.instance_id,
                    actor_user_id=actor_user_id,
                    action="GROUP_UNBOUND",
                    details=json.dumps(
                        {"chat_id": binding.chat_id, "chat_title": binding.chat_title},
                        ensure_ascii=False,
                    ),
                    created_at=now,
                )
            )
            return True

    async def get_template(self) -> ReplyTemplate:
        async with self.sessions() as session:
            template = await session.scalar(
                select(ReplyTemplate).where(ReplyTemplate.bot_instance_id == self.instance_id)
            )
            if template is None:
                raise RuntimeError("Reply template is missing")
            return template

    async def get_start_page(self) -> StartPage:
        async with self.sessions() as session:
            start_page = await session.scalar(
                select(StartPage).where(StartPage.bot_instance_id == self.instance_id)
            )
            if start_page is None:
                raise RuntimeError("Start page is missing")
            return start_page

    @staticmethod
    def validate_start_page_text(text_value: str) -> None:
        if not text_value.strip():
            raise ValueError("首页文案不能为空")
        if len(text_value) > 1024:
            raise ValueError("首页文案不能超过 1024 个字符")

    async def update_start_page_text(self, text_value: str, actor_user_id: int) -> StartPage:
        self.validate_start_page_text(text_value)
        now = utc_now()
        async with self.sessions.begin() as session:
            start_page = await session.scalar(
                select(StartPage).where(StartPage.bot_instance_id == self.instance_id)
            )
            if start_page is None:
                raise RuntimeError("Start page is missing")
            start_page.text = text_value
            start_page.updated_by = actor_user_id
            start_page.updated_at = now
            session.add(
                AuditLog(
                    bot_instance_id=self.instance_id,
                    actor_user_id=actor_user_id,
                    action="START_PAGE_TEXT_UPDATED",
                    details=json.dumps({"length": len(text_value)}),
                    created_at=now,
                )
            )
            return start_page

    async def update_start_page_photo(
        self, photo_file_id: str | None, actor_user_id: int
    ) -> StartPage:
        if photo_file_id is not None and not photo_file_id.strip():
            raise ValueError("首页图片标识不能为空")
        now = utc_now()
        async with self.sessions.begin() as session:
            start_page = await session.scalar(
                select(StartPage).where(StartPage.bot_instance_id == self.instance_id)
            )
            if start_page is None:
                raise RuntimeError("Start page is missing")
            start_page.photo_file_id = photo_file_id
            start_page.updated_by = actor_user_id
            start_page.updated_at = now
            session.add(
                AuditLog(
                    bot_instance_id=self.instance_id,
                    actor_user_id=actor_user_id,
                    action="START_PAGE_MEDIA_UPDATED",
                    details=json.dumps({"has_photo": photo_file_id is not None}),
                    created_at=now,
                )
            )
            return start_page

    @staticmethod
    def validate_template(template_text: str) -> None:
        if not template_text.strip():
            raise ValueError("文案不能为空")
        if len(template_text) > 3500:
            raise ValueError("文案不能超过 3500 个字符")
        try:
            fields = {
                field_name
                for _, field_name, _, _ in Formatter().parse(template_text)
                if field_name
            }
        except ValueError as exc:
            raise ValueError("文案中的大括号格式不正确") from exc
        unknown = fields - ALLOWED_TEMPLATE_FIELDS
        if unknown:
            raise ValueError(f"不支持的变量：{', '.join(sorted(unknown))}")

    async def update_template(self, text_value: str, actor_user_id: int) -> ReplyTemplate:
        self.validate_template(text_value)
        now = utc_now()
        async with self.sessions.begin() as session:
            template = await session.scalar(
                select(ReplyTemplate).where(ReplyTemplate.bot_instance_id == self.instance_id)
            )
            if template is None:
                raise RuntimeError("Reply template is missing")
            template.text = text_value
            template.version += 1
            template.updated_by = actor_user_id
            template.updated_at = now
            session.add(
                AuditLog(
                    bot_instance_id=self.instance_id,
                    actor_user_id=actor_user_id,
                    action="TEMPLATE_UPDATED",
                    details=json.dumps({"version": template.version}),
                    created_at=now,
                )
            )
            return template

    async def list_buttons(self) -> list[TemplateButton]:
        async with self.sessions() as session:
            result = await session.scalars(
                select(TemplateButton)
                .where(
                    TemplateButton.bot_instance_id == self.instance_id,
                    TemplateButton.enabled.is_(True),
                )
                .order_by(TemplateButton.row_number, TemplateButton.column_number)
            )
            return list(result)

    async def replace_buttons(
        self, rows: list[list[tuple[str, str]]], actor_user_id: int
    ) -> None:
        now = utc_now()
        async with self.sessions.begin() as session:
            await session.execute(
                delete(TemplateButton).where(TemplateButton.bot_instance_id == self.instance_id)
            )
            for row_number, row in enumerate(rows):
                for column_number, (button_text, url) in enumerate(row):
                    session.add(
                        TemplateButton(
                            bot_instance_id=self.instance_id,
                            text=button_text,
                            url=url,
                            row_number=row_number,
                            column_number=column_number,
                        )
                    )
            session.add(
                AuditLog(
                    bot_instance_id=self.instance_id,
                    actor_user_id=actor_user_id,
                    action="BUTTONS_REPLACED",
                    details=json.dumps({"button_count": sum(map(len, rows))}),
                    created_at=now,
                )
            )

    async def list_start_page_buttons(self) -> list[StartPageButton]:
        async with self.sessions() as session:
            result = await session.scalars(
                select(StartPageButton)
                .where(
                    StartPageButton.bot_instance_id == self.instance_id,
                    StartPageButton.enabled.is_(True),
                )
                .order_by(StartPageButton.row_number, StartPageButton.column_number)
            )
            return list(result)

    async def replace_start_page_buttons(
        self, rows: list[list[tuple[str, str]]], actor_user_id: int
    ) -> None:
        now = utc_now()
        async with self.sessions.begin() as session:
            await session.execute(
                delete(StartPageButton).where(StartPageButton.bot_instance_id == self.instance_id)
            )
            for row_number, row in enumerate(rows):
                for column_number, (button_text, url) in enumerate(row):
                    session.add(
                        StartPageButton(
                            bot_instance_id=self.instance_id,
                            text=button_text,
                            url=url,
                            row_number=row_number,
                            column_number=column_number,
                        )
                    )
            session.add(
                AuditLog(
                    bot_instance_id=self.instance_id,
                    actor_user_id=actor_user_id,
                    action="START_PAGE_BUTTONS_REPLACED",
                    details=json.dumps({"button_count": sum(map(len, rows))}),
                    created_at=now,
                )
            )

    @staticmethod
    def parse_button_definition(value: str) -> list[list[tuple[str, str]]]:
        if not value.strip() or value.strip().upper() == "CLEAR":
            return []
        parsed: dict[int, list[tuple[int, str, str]]] = {}
        for line_number, source_line in enumerate(value.splitlines(), start=1):
            if not source_line.strip():
                continue
            parts = [item.strip() for item in source_line.split("|", maxsplit=3)]
            if len(parts) != 4:
                raise ValueError(f"第 {line_number} 行格式错误")
            try:
                row_number = int(parts[0])
                column_number = int(parts[1])
            except ValueError as exc:
                raise ValueError(f"第 {line_number} 行的行列号必须是整数") from exc
            button_text, url = parts[2], parts[3]
            if row_number < 1 or column_number not in (1, 2):
                raise ValueError(f"第 {line_number} 行仅支持从第1行开始、每行最多2个按钮")
            if not button_text or len(button_text) > 64:
                raise ValueError(f"第 {line_number} 行按钮文字长度必须为 1～64")
            if not BotService.is_valid_button_url(url):
                raise ValueError(
                    f"第 {line_number} 行 URL 格式无效，必须是完整的 "
                    "http://、https:// 或 tg:// 地址"
                )
            parsed.setdefault(row_number, []).append((column_number, button_text, url))
        rows: list[list[tuple[str, str]]] = []
        for row_number in sorted(parsed):
            items = sorted(parsed[row_number])
            columns = [item[0] for item in items]
            if len(set(columns)) != len(columns):
                raise ValueError(f"第 {row_number} 行存在重复列号")
            rows.append([(item[1], item[2]) for item in items])
        if sum(map(len, rows)) > 20:
            raise ValueError("按钮总数不能超过 20 个")
        return rows

    @staticmethod
    def is_valid_button_url(url: str) -> bool:
        if not url or any(character.isspace() or ord(character) < 32 for character in url):
            return False
        try:
            parsed = urlsplit(url)
            _ = parsed.port
        except ValueError:
            return False
        if parsed.scheme in {"http", "https"}:
            if not parsed.hostname or parsed.username is not None or parsed.password is not None:
                return False
            try:
                hostname = parsed.hostname.encode("idna").decode("ascii")
            except UnicodeError:
                return False
            return all(HTTP_HOST_LABEL.fullmatch(label) for label in hostname.split("."))
        if parsed.scheme == "tg":
            return bool(parsed.netloc)
        return False

    async def record_photo(self, message: Message) -> RecordResult:
        binding = await self.active_binding()
        if binding is None or binding.chat_id != message.chat.id:
            return RecordResult(accepted=False)

        now = utc_now()
        sent_at = ensure_utc(message.date)
        media_group_id = message.media_group_id
        submission_key = (
            f"album:{media_group_id}" if media_group_id else f"message:{message.message_id}"
        )
        settle_seconds = self.album_settle_seconds if media_group_id else 0
        reply_not_before = now + timedelta(seconds=settle_seconds)

        async with self._record_lock:
            async with self.sessions.begin() as session:
                existing_part = await session.scalar(
                    select(SubmissionPart).where(
                        SubmissionPart.bot_instance_id == self.instance_id,
                        SubmissionPart.chat_id == message.chat.id,
                        SubmissionPart.message_id == message.message_id,
                    )
                )
                if existing_part is not None:
                    return RecordResult(
                        accepted=True, created=False, submission_id=existing_part.submission_id
                    )

                submission = await session.scalar(
                    select(Submission).where(
                        Submission.bot_instance_id == self.instance_id,
                        Submission.chat_id == message.chat.id,
                        Submission.submission_key == submission_key,
                    )
                )
                created = submission is None
                if submission is None:
                    from_user = message.from_user
                    sender_chat = message.sender_chat
                    if sender_chat is not None:
                        display_name = sender_chat.title or "匿名群组身份"
                        user_id = None
                        sender_chat_id = sender_chat.id
                        first_name = None
                        last_name = None
                        username = sender_chat.username
                    elif from_user is not None:
                        display_name = from_user.full_name
                        user_id = from_user.id
                        sender_chat_id = None
                        first_name = from_user.first_name
                        last_name = from_user.last_name
                        username = from_user.username
                    else:
                        display_name = "未知发送者"
                        user_id = None
                        sender_chat_id = None
                        first_name = None
                        last_name = None
                        username = None
                    submission = Submission(
                        bot_instance_id=self.instance_id,
                        group_binding_id=binding.id,
                        chat_id=message.chat.id,
                        chat_title=binding.chat_title,
                        submission_key=submission_key,
                        primary_message_id=message.message_id,
                        media_group_id=media_group_id,
                        telegram_user_id=user_id,
                        sender_chat_id=sender_chat_id,
                        first_name_snapshot=first_name,
                        last_name_snapshot=last_name,
                        display_name_snapshot=display_name,
                        username_snapshot=username,
                        photo_count=0,
                        sent_at=sent_at,
                        received_at=now,
                        reply_not_before=reply_not_before,
                        reply_status=ReplyStatus.PENDING,
                    )
                    session.add(submission)
                    await session.flush()
                else:
                    submission.reply_not_before = max(
                        ensure_utc(submission.reply_not_before), reply_not_before
                    )
                    if sent_at < ensure_utc(submission.sent_at):
                        submission.sent_at = sent_at
                        submission.primary_message_id = message.message_id

                session.add(
                    SubmissionPart(
                        submission_id=submission.id,
                        bot_instance_id=self.instance_id,
                        chat_id=message.chat.id,
                        message_id=message.message_id,
                        received_at=now,
                    )
                )
                submission.photo_count += 1
                return RecordResult(accepted=True, created=created, submission_id=submission.id)

    async def next_pending_reply(self, now: datetime) -> Submission | None:
        async with self.sessions.begin() as session:
            submission = await session.scalar(
                select(Submission)
                .where(
                    Submission.bot_instance_id == self.instance_id,
                    Submission.reply_status.in_([ReplyStatus.PENDING, ReplyStatus.RETRYING]),
                    Submission.reply_not_before <= now,
                    or_(Submission.next_retry_at.is_(None), Submission.next_retry_at <= now),
                )
                .order_by(Submission.sent_at)
                .limit(1)
            )
            if submission is None:
                return None
            submission.reply_status = ReplyStatus.SENDING
            submission.reply_attempts += 1
            submission.reply_error = None
            await session.flush()
            session.expunge(submission)
            return submission

    async def reply_payload(
        self, submission: Submission
    ) -> tuple[str, InlineKeyboardMarkup | None, int]:
        template = await self.get_template()
        buttons = await self.list_buttons()
        values = {
            "tg_id": html.escape(str(submission.telegram_user_id or "未知")),
            "display_name": html.escape(submission.display_name_snapshot),
            "username": html.escape(
                f"@{submission.username_snapshot}" if submission.username_snapshot else "—"
            ),
            "send_time": ensure_utc(submission.sent_at)
            .astimezone(ZoneInfo(self.timezone))
            .strftime("%Y-%m-%d %H:%M:%S"),
            "group_name": html.escape(submission.chat_title),
            "message_id": str(submission.primary_message_id),
        }
        rendered = template.text.format_map(values)
        keyboard = self.build_keyboard(buttons)
        return rendered, keyboard, template.version

    async def start_page_payload(self) -> tuple[str, str | None, InlineKeyboardMarkup | None]:
        start_page = await self.get_start_page()
        buttons = await self.list_start_page_buttons()
        return start_page.text, start_page.photo_file_id, self.build_keyboard(buttons)

    @staticmethod
    def build_keyboard(
        buttons: list[TemplateButton] | list[StartPageButton],
    ) -> InlineKeyboardMarkup | None:
        valid_buttons = []
        for button in buttons:
            if BotService.is_valid_button_url(button.url):
                valid_buttons.append(button)
            else:
                logger.error("Skipping invalid template button URL button_id=%s", button.id)
        if not valid_buttons:
            return None
        rows: dict[int, list[TemplateButton]] = {}
        for button in valid_buttons:
            rows.setdefault(button.row_number, []).append(button)
        keyboard = [
            [
                InlineKeyboardButton(text=button.text, url=button.url)
                for button in sorted(row, key=lambda item: item.column_number)
            ]
            for _, row in sorted(rows.items())
        ]
        return InlineKeyboardMarkup(inline_keyboard=keyboard)

    async def mark_reply_sent(self, submission_id: int, message_id: int, version: int) -> None:
        async with self.sessions.begin() as session:
            await session.execute(
                update(Submission)
                .where(Submission.id == submission_id)
                .values(
                    reply_status=ReplyStatus.SENT,
                    reply_message_id=message_id,
                    replied_at=utc_now(),
                    next_retry_at=None,
                    reply_error=None,
                    template_version=version,
                )
            )

    async def mark_reply_failed(
        self,
        submission_id: int,
        error: str,
        *,
        retry_after_seconds: float | None,
        max_attempts: int,
    ) -> None:
        async with self.sessions.begin() as session:
            submission = await session.get(Submission, submission_id)
            if submission is None:
                return
            retryable = submission.reply_attempts < max_attempts
            if retryable:
                delay = retry_after_seconds or min(300, 2 ** submission.reply_attempts)
                submission.reply_status = ReplyStatus.RETRYING
                submission.next_retry_at = utc_now() + timedelta(seconds=delay)
            else:
                submission.reply_status = ReplyStatus.FAILED
                submission.next_retry_at = None
            submission.reply_error = error[:2000]

    async def export_rows(self, start_utc: datetime, end_utc: datetime) -> list[Submission]:
        async with self.sessions() as session:
            result = await session.scalars(
                select(Submission)
                .where(
                    Submission.bot_instance_id == self.instance_id,
                    Submission.sent_at >= start_utc,
                    Submission.sent_at < end_utc,
                )
                .order_by(Submission.sent_at, Submission.id)
            )
            return list(result)

    async def statistics(self) -> dict[str, int | datetime | None]:
        async with self.sessions() as session:
            total = await session.scalar(
                select(func.count(Submission.id)).where(
                    Submission.bot_instance_id == self.instance_id
                )
            )
            pending = await session.scalar(
                select(func.count(Submission.id)).where(
                    Submission.bot_instance_id == self.instance_id,
                    Submission.reply_status.in_([ReplyStatus.PENDING, ReplyStatus.RETRYING]),
                )
            )
            failed = await session.scalar(
                select(func.count(Submission.id)).where(
                    Submission.bot_instance_id == self.instance_id,
                    Submission.reply_status == ReplyStatus.FAILED,
                )
            )
            last_sent = await session.scalar(
                select(func.max(Submission.sent_at)).where(
                    Submission.bot_instance_id == self.instance_id
                )
            )
        return {
            "total": total or 0,
            "pending": pending or 0,
            "failed": failed or 0,
            "last_sent": last_sent,
        }
