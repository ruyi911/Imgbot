from __future__ import annotations

import html
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram import Bot, F, Router
from aiogram.enums import ChatMemberStatus, ChatType
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from imgbot.config import Settings
from imgbot.exporter import build_csv, build_xlsx, export_filename
from imgbot.keyboards import (
    admin_menu,
    administrator_management,
    confirm_binding,
    confirm_delete_administrator,
    confirm_unbind,
    export_formats,
    export_ranges,
)
from imgbot.service import BotService, PendingBinding
from imgbot.states import (
    AdministratorStates,
    BindingStates,
    ButtonStates,
    ExportStates,
    StartPageStates,
    TemplateStates,
)
from imgbot.timeutils import ensure_utc, local_day_bounds, parse_local_range, utc_now

router = Router(name="admin")
router.message.filter(F.chat.type == ChatType.PRIVATE)
router.callback_query.filter(F.message.chat.type == ChatType.PRIVATE)
logger = logging.getLogger(__name__)


def is_super_admin(user_id: int, settings: Settings) -> bool:
    return user_id in settings.super_admin_ids


async def has_admin_access(
    user_id: int, settings: Settings, service: BotService
) -> bool:
    return is_super_admin(user_id, settings) or await service.is_admin(user_id)


def parse_administrator_input(value: str) -> tuple[int, str | None]:
    lines = value.splitlines()
    if not lines or len(lines) > 2:
        raise ValueError("格式错误，请使用第一行 TG ID、第二行名称，名称可不填")
    try:
        telegram_user_id = int(lines[0].strip())
    except ValueError as exc:
        raise ValueError("第一行 TG ID 必须是正整数") from exc
    if telegram_user_id <= 0:
        raise ValueError("第一行 TG ID 必须是正整数")
    display_name = lines[1].strip() if len(lines) == 2 else None
    if display_name and len(display_name) > 100:
        raise ValueError("管理员名称不能超过 100 个字符")
    return telegram_user_id, display_name or None


async def reject_message(message: Message) -> None:
    await message.answer("Hello")


async def reject_callback(callback: CallbackQuery) -> None:
    await callback.answer("Hello", show_alert=True)


def admin_preview(value: str, *, limit: int = 3000) -> str:
    rendered: list[str] = []
    length = 0
    for character in value:
        escaped = html.escape(character)
        if length + len(escaped) > limit:
            return "".join(rendered) + "\n…（内容过长，已截断显示）"
        rendered.append(escaped)
        length += len(escaped)
    return "".join(rendered)


async def render_home(
    target: Message,
    actor_user_id: int,
    service: BotService,
    settings: Settings,
) -> None:
    binding = await service.active_binding()
    actor_is_super = is_super_admin(actor_user_id, settings)
    role_name = "超级管理员" if actor_is_super else "管理员"
    if binding:
        text = (
            "<b>图片登记机器人管理</b>\n\n"
            f"实例：<code>{html.escape(settings.bot_instance_id)}</code>\n"
            f"当前群组：{html.escape(binding.chat_title)}\n"
            f"群组 ID：<code>{binding.chat_id}</code>\n"
            f"时区：印度 +5.5\n"
            f"当前角色：{role_name}\n"
            "状态：✅ 运行中"
        )
    else:
        text = (
            "<b>图片登记机器人管理</b>\n\n"
            f"实例：<code>{html.escape(settings.bot_instance_id)}</code>\n"
            "当前群组：未绑定\n"
            f"时区：印度 +5.5\n"
            f"当前角色：{role_name}"
        )
    await target.answer(
        text,
        reply_markup=admin_menu(binding is not None, is_super_admin=actor_is_super),
    )


async def render_start_page(target: Message, service: BotService) -> None:
    text, photo_file_id, keyboard = await service.start_page_payload()
    if photo_file_id is not None:
        await target.answer_photo(
            photo=photo_file_id, caption=text, reply_markup=keyboard
        )
        return
    await target.answer(text, reply_markup=keyboard)


@router.message(CommandStart())
async def start(
    message: Message, state: FSMContext, service: BotService, settings: Settings
) -> None:
    await state.clear()
    await render_start_page(message, service)
    if message.from_user is not None and await has_admin_access(
        message.from_user.id, settings, service
    ):
        await render_home(message, message.from_user.id, service, settings)


@router.callback_query(F.data == "admin:home")
async def home_callback(
    callback: CallbackQuery, state: FSMContext, service: BotService, settings: Settings
) -> None:
    if not await has_admin_access(callback.from_user.id, settings, service):
        await reject_callback(callback)
        return
    await state.clear()
    await callback.answer()
    await render_home(callback.message, callback.from_user.id, service, settings)


@router.callback_query(F.data == "admin:bind")
async def begin_binding(
    callback: CallbackQuery, state: FSMContext, service: BotService, settings: Settings
) -> None:
    if not await has_admin_access(callback.from_user.id, settings, service):
        await reject_callback(callback)
        return
    if await service.active_binding() is not None:
        await callback.answer("当前实例已经绑定群组", show_alert=True)
        return
    await state.set_state(BindingStates.waiting_chat_id)
    await callback.answer()
    await callback.message.answer(
        "请发送要绑定的群组 ID，例如：\n<code>-1001234567890</code>\n\n"
        "绑定前请先把本机器人加入该群并设为管理员。"
    )


@router.message(BindingStates.waiting_chat_id)
async def receive_chat_id(
    message: Message,
    state: FSMContext,
    bot: Bot,
    service: BotService,
    settings: Settings,
) -> None:
    if message.from_user is None or not await has_admin_access(
        message.from_user.id, settings, service
    ):
        await reject_message(message)
        return
    try:
        chat_id = int((message.text or "").strip())
    except ValueError:
        await message.answer("群组 ID 必须是整数，例如 <code>-1001234567890</code>。")
        return
    try:
        chat = await bot.get_chat(chat_id)
        if chat.type not in {ChatType.GROUP, ChatType.SUPERGROUP}:
            await message.answer("该 ID 不是群组或超级群组。")
            return
        me = await bot.get_me()
        bot_member = await bot.get_chat_member(chat_id, me.id)
        actor_member = await bot.get_chat_member(chat_id, message.from_user.id)
    except (TelegramBadRequest, TelegramForbiddenError):
        await message.answer(
            "无法验证该群。请确认群组 ID 正确，并且本机器人已经加入群组。\n"
        )
        return
    admin_statuses = {ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR}
    if bot_member.status not in admin_statuses:
        await message.answer("机器人目前不是该群管理员，绑定失败。")
        return
    if actor_member.status not in admin_statuses:
        await message.answer("你目前不是该群管理员，绑定失败。")
        return
    pending = PendingBinding(
        chat_id=chat.id,
        chat_title=chat.title or str(chat.id),
        chat_type=chat.type,
    )
    await state.update_data(
        pending_chat_id=pending.chat_id,
        pending_chat_title=pending.chat_title,
        pending_chat_type=str(pending.chat_type),
    )
    await state.set_state(BindingStates.confirming)
    await message.answer(
        "<b>请确认绑定信息</b>\n\n"
        f"群组名称：{html.escape(pending.chat_title)}\n"
        f"群组 ID：<code>{pending.chat_id}</code>\n"
        "机器人权限：✅ 管理员\n"
        "你的身份：✅ 管理员\n"
        f"业务时区：印度 +5.5\n",
        reply_markup=confirm_binding(),
    )


@router.callback_query(BindingStates.confirming, F.data == "bind:confirm")
async def confirm_group_binding(
    callback: CallbackQuery,
    state: FSMContext,
    bot: Bot,
    service: BotService,
    settings: Settings,
) -> None:
    if not await has_admin_access(callback.from_user.id, settings, service):
        await reject_callback(callback)
        return
    data = await state.get_data()
    pending = PendingBinding(
        chat_id=int(data["pending_chat_id"]),
        chat_title=str(data["pending_chat_title"]),
        chat_type=str(data["pending_chat_type"]),
    )
    # Recheck both memberships at the moment the binding becomes active.
    try:
        me = await bot.get_me()
        bot_member = await bot.get_chat_member(pending.chat_id, me.id)
        actor_member = await bot.get_chat_member(pending.chat_id, callback.from_user.id)
    except (TelegramBadRequest, TelegramForbiddenError):
        await callback.answer("群权限验证失败，请重新绑定", show_alert=True)
        await state.clear()
        return
    admin_statuses = {ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR}
    if (
        bot_member.status not in admin_statuses
        or actor_member.status not in admin_statuses
    ):
        await callback.answer("机器人或你的管理员权限已发生变化", show_alert=True)
        await state.clear()
        return
    try:
        await service.bind_group(pending, callback.from_user.id)
    except ValueError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await state.clear()
    await callback.answer("绑定成功")
    await callback.message.answer("✅ 群组绑定成功，机器人现在只处理该群的照片。")
    await render_home(callback.message, callback.from_user.id, service, settings)


@router.callback_query(F.data == "bind:cancel")
async def cancel_binding(
    callback: CallbackQuery, state: FSMContext, service: BotService, settings: Settings
) -> None:
    if not await has_admin_access(callback.from_user.id, settings, service):
        await reject_callback(callback)
        return
    await state.clear()
    await callback.answer("已取消")
    await render_home(callback.message, callback.from_user.id, service, settings)


@router.callback_query(F.data == "admin:unbind")
async def begin_unbind(
    callback: CallbackQuery, service: BotService, settings: Settings
) -> None:
    if not await has_admin_access(callback.from_user.id, settings, service):
        await reject_callback(callback)
        return
    await callback.answer()
    await callback.message.answer(
        "解除后将停止记录新消息，历史数据不会删除。确定解除当前群组吗？",
        reply_markup=confirm_unbind(),
    )


@router.callback_query(F.data == "unbind:confirm")
async def confirm_unbind_group(
    callback: CallbackQuery, service: BotService, settings: Settings
) -> None:
    if not await has_admin_access(callback.from_user.id, settings, service):
        await reject_callback(callback)
        return
    changed = await service.unbind_group(callback.from_user.id)
    await callback.answer("已解除" if changed else "当前没有绑定群组", show_alert=True)
    await render_home(callback.message, callback.from_user.id, service, settings)


@router.callback_query(F.data == "admin:template")
async def begin_template(
    callback: CallbackQuery, state: FSMContext, service: BotService, settings: Settings
) -> None:
    if not await has_admin_access(callback.from_user.id, settings, service):
        await reject_callback(callback)
        return
    template = await service.get_template()
    await state.set_state(TemplateStates.waiting_text)
    await callback.answer()
    await callback.message.answer(
        "<b>当前回复文案</b>\n\n"
        f"<pre>{html.escape(template.text)}</pre>\n"
        "请直接发送新文案。支持变量：\n"
        "<code>{tg_id} {display_name} {username} {send_time} "
        "{group_name} {message_id}</code>\n\n"
        "文案使用 Telegram HTML 格式。发送 /cancel 取消。"
    )


@router.message(Command("cancel"))
async def cancel_state(
    message: Message, state: FSMContext, service: BotService, settings: Settings
) -> None:
    if message.from_user is None or not await has_admin_access(
        message.from_user.id, settings, service
    ):
        await reject_message(message)
        return
    await state.clear()
    await message.answer("已取消。")
    await render_home(message, message.from_user.id, service, settings)


@router.callback_query(F.data == "admin:start_media")
async def begin_start_page_media(
    callback: CallbackQuery, state: FSMContext, service: BotService, settings: Settings
) -> None:
    if not await has_admin_access(callback.from_user.id, settings, service):
        await reject_callback(callback)
        return
    start_page = await service.get_start_page()
    await state.set_state(StartPageStates.waiting_photo)
    await callback.answer()
    if start_page.photo_file_id is not None:
        await callback.message.answer_photo(photo=start_page.photo_file_id)
    await callback.message.answer(
        "<b>首页媒体</b>\n\n"
        f"当前图片：{'已设置' if start_page.photo_file_id else '未设置'}\n\n"
        "请直接发送要配置的图片\n"
        "发送 <code>CLEAR</code> 删除当前图片，发送 /cancel 取消。"
    )


@router.message(StartPageStates.waiting_photo, F.photo)
async def receive_start_page_media(
    message: Message, state: FSMContext, service: BotService, settings: Settings
) -> None:
    if message.from_user is None or not await has_admin_access(
        message.from_user.id, settings, service
    ):
        await reject_message(message)
        return
    await service.update_start_page_photo(
        message.photo[-1].file_id, message.from_user.id
    )
    await state.clear()
    await message.answer("✅ 首页图片已保存，已覆盖原图片。")
    await render_home(message, message.from_user.id, service, settings)


@router.message(StartPageStates.waiting_photo)
async def receive_start_page_media_clear(
    message: Message, state: FSMContext, service: BotService, settings: Settings
) -> None:
    if message.from_user is None or not await has_admin_access(
        message.from_user.id, settings, service
    ):
        await reject_message(message)
        return
    if (message.text or "").strip().upper() != "CLEAR":
        await message.answer(
            "请直接发送一张图片，或发送 <code>CLEAR</code> 删除当前图片。"
        )
        return
    await service.update_start_page_photo(None, message.from_user.id)
    await state.clear()
    await message.answer("✅ 首页图片已删除。")
    await render_home(message, message.from_user.id, service, settings)


@router.callback_query(F.data == "admin:start_text")
async def begin_start_page_text(
    callback: CallbackQuery, state: FSMContext, service: BotService, settings: Settings
) -> None:
    if not await has_admin_access(callback.from_user.id, settings, service):
        await reject_callback(callback)
        return
    start_page = await service.get_start_page()
    await state.set_state(StartPageStates.waiting_text)
    await callback.answer()
    await callback.message.answer(
        "<b>当前首页文案</b>\n\n"
        f"<pre>{admin_preview(start_page.text)}</pre>\n\n"
        "请直接发送新的首页文案。文案使用 Telegram HTML 格式，最多 1024 个字符。\n"
        "发送 /cancel 取消。"
    )


@router.message(StartPageStates.waiting_text)
async def receive_start_page_text(
    message: Message, state: FSMContext, service: BotService, settings: Settings
) -> None:
    if message.from_user is None or not await has_admin_access(
        message.from_user.id, settings, service
    ):
        await reject_message(message)
        return
    try:
        await service.update_start_page_text(message.text or "", message.from_user.id)
    except ValueError as exc:
        await message.answer(f"首页文案无法保存：{html.escape(str(exc))}")
        return
    await state.clear()
    await message.answer("✅ 首页文案已保存。")
    await render_home(message, message.from_user.id, service, settings)


@router.callback_query(F.data == "admin:start_buttons")
async def begin_start_page_buttons(
    callback: CallbackQuery, state: FSMContext, service: BotService, settings: Settings
) -> None:
    if not await has_admin_access(callback.from_user.id, settings, service):
        await reject_callback(callback)
        return
    buttons = await service.list_start_page_buttons()
    current = (
        "\n".join(
            f"{button.row_number + 1}|{button.column_number + 1}|{button.text}|{button.url}"
            for button in buttons
        )
        or "（当前没有按钮）"
    )
    await state.set_state(StartPageStates.waiting_buttons)
    await callback.answer()
    await callback.message.answer(
        "<b>当前首页按钮</b>\n"
        f"<pre>{admin_preview(current)}</pre>\n\n"
        "请发送完整的新配置，每行格式：\n"
        "<code>行|列|按钮文字|URL</code>\n\n"
        "示例：\n"
        "<pre>1|1|参加其他活动|https://example.com/events\n"
        "2|1|VIP群|https://t.me/example_vip\n"
        "2|2|官方频道|https://t.me/example</pre>\n"
        "每行最多两个按钮。发送 CLEAR 清空按钮，发送 /cancel 取消。"
    )


@router.message(StartPageStates.waiting_buttons)
async def receive_start_page_buttons(
    message: Message, state: FSMContext, service: BotService, settings: Settings
) -> None:
    if message.from_user is None or not await has_admin_access(
        message.from_user.id, settings, service
    ):
        await reject_message(message)
        return
    try:
        rows = service.parse_button_definition(message.text or "")
        await service.replace_start_page_buttons(rows, message.from_user.id)
    except ValueError as exc:
        await message.answer(f"首页按钮无法保存：{html.escape(str(exc))}")
        return
    await state.clear()
    await message.answer(f"✅ 已保存 {sum(map(len, rows))} 个首页按钮。")
    await render_home(message, message.from_user.id, service, settings)


@router.message(TemplateStates.waiting_text)
async def receive_template(
    message: Message, state: FSMContext, service: BotService, settings: Settings
) -> None:
    if message.from_user is None or not await has_admin_access(
        message.from_user.id, settings, service
    ):
        await reject_message(message)
        return
    value = message.text or ""
    try:
        template = await service.update_template(value, message.from_user.id)
    except ValueError as exc:
        await message.answer(f"文案无法保存：{html.escape(str(exc))}")
        return
    await state.clear()
    await message.answer(f"✅ 文案已保存，版本：{template.version}")
    await render_home(message, message.from_user.id, service, settings)


@router.callback_query(F.data == "admin:buttons")
async def begin_buttons(
    callback: CallbackQuery, state: FSMContext, service: BotService, settings: Settings
) -> None:
    if not await has_admin_access(callback.from_user.id, settings, service):
        await reject_callback(callback)
        return
    buttons = await service.list_buttons()
    current = (
        "\n".join(
            f"{button.row_number + 1}|{button.column_number + 1}|{button.text}|{button.url}"
            for button in buttons
        )
        or "（当前没有按钮）"
    )
    await state.set_state(ButtonStates.waiting_definition)
    await callback.answer()
    await callback.message.answer(
        "<b>当前按钮配置</b>\n"
        f"<pre>{html.escape(current)}</pre>\n\n"
        "请发送完整的新配置，每行格式：\n"
        "<code>行|列|按钮文字|URL</code>\n\n"
        "示例：\n"
        "<pre>1|1|参加其他活动|https://example.com/events\n"
        "2|1|VIP群|https://t.me/example_vip\n"
        "2|2|官方频道|https://t.me/example</pre>\n"
        "每行最多两个按钮。发送 CLEAR 清空按钮，发送 /cancel 取消。"
    )


@router.message(ButtonStates.waiting_definition)
async def receive_buttons(
    message: Message, state: FSMContext, service: BotService, settings: Settings
) -> None:
    if message.from_user is None or not await has_admin_access(
        message.from_user.id, settings, service
    ):
        await reject_message(message)
        return
    try:
        rows = service.parse_button_definition(message.text or "")
        await service.replace_buttons(rows, message.from_user.id)
    except ValueError as exc:
        await message.answer(f"按钮配置无法保存：{html.escape(str(exc))}")
        return
    await state.clear()
    await message.answer(f"✅ 已保存 {sum(map(len, rows))} 个按钮。")
    await render_home(message, message.from_user.id, service, settings)


@router.callback_query(F.data == "admin:export")
async def begin_export(
    callback: CallbackQuery, service: BotService, settings: Settings
) -> None:
    if not await has_admin_access(callback.from_user.id, settings, service):
        await reject_callback(callback)
        return
    await callback.answer()
    await callback.message.answer(
        "请选择导出时间范围。所有时间均按印度时区 "
        f"<code>{html.escape(settings.business_timezone)}</code> 解释。",
        reply_markup=export_ranges(),
    )


@router.callback_query(F.data.startswith("export:"))
async def select_export_range(
    callback: CallbackQuery, state: FSMContext, service: BotService, settings: Settings
) -> None:
    if not await has_admin_access(callback.from_user.id, settings, service):
        await reject_callback(callback)
        return
    choice = callback.data.split(":", maxsplit=1)[1]
    timezone = ZoneInfo(settings.business_timezone)
    today = datetime.now(timezone).date()
    if choice == "custom":
        await state.set_state(ExportStates.waiting_custom_range)
        await callback.answer()
        await callback.message.answer(
            "请输入印度时间范围：\n"
            "<code>YYYY-MM-DD HH:MM | YYYY-MM-DD HH:MM</code>\n\n"
            "例如：\n<code>2026-08-01 00:00 | 2026-08-03 23:59</code>"
        )
        return
    if choice == "today":
        start_utc, end_utc = local_day_bounds(today, timezone)
    elif choice == "yesterday":
        start_utc, end_utc = local_day_bounds(today - timedelta(days=1), timezone)
    elif choice == "7days":
        start_utc, _ = local_day_bounds(today - timedelta(days=6), timezone)
        _, end_utc = local_day_bounds(today, timezone)
    else:
        await callback.answer("未知时间范围", show_alert=True)
        return
    await state.update_data(
        start_utc=start_utc.isoformat(), end_utc=end_utc.isoformat()
    )
    await state.set_state(ExportStates.waiting_format)
    await callback.answer()
    await callback.message.answer("请选择文件格式：", reply_markup=export_formats())


@router.message(ExportStates.waiting_custom_range)
async def receive_custom_range(
    message: Message, state: FSMContext, service: BotService, settings: Settings
) -> None:
    if message.from_user is None or not await has_admin_access(
        message.from_user.id, settings, service
    ):
        await reject_message(message)
        return
    try:
        start_utc, end_utc = parse_local_range(
            message.text or "", ZoneInfo(settings.business_timezone)
        )
    except ValueError as exc:
        await message.answer(html.escape(str(exc)))
        return
    if end_utc - start_utc > timedelta(days=366):
        await message.answer("单次导出范围不能超过 366 天。")
        return
    await state.update_data(
        start_utc=start_utc.isoformat(), end_utc=end_utc.isoformat()
    )
    await state.set_state(ExportStates.waiting_format)
    await message.answer("请选择文件格式：", reply_markup=export_formats())


@router.callback_query(ExportStates.waiting_format, F.data.startswith("exportfmt:"))
async def create_export(
    callback: CallbackQuery, state: FSMContext, service: BotService, settings: Settings
) -> None:
    if not await has_admin_access(callback.from_user.id, settings, service):
        await reject_callback(callback)
        return
    suffix = callback.data.split(":", maxsplit=1)[1]
    if suffix not in {"xlsx", "csv"}:
        await callback.answer("不支持的格式", show_alert=True)
        return
    await callback.answer("正在生成文件")
    try:
        data = await state.get_data()
        start_utc = datetime.fromisoformat(data["start_utc"]).astimezone(
            ZoneInfo("UTC")
        )
        end_utc = datetime.fromisoformat(data["end_utc"]).astimezone(ZoneInfo("UTC"))
        rows = await service.export_rows(start_utc, end_utc)
        timezone = ZoneInfo(settings.business_timezone)
        payload = (
            build_xlsx(rows, timezone)
            if suffix == "xlsx"
            else build_csv(rows, timezone)
        )
        filename = export_filename(start_utc, end_utc, suffix)
        await callback.message.answer_document(
            BufferedInputFile(payload, filename=filename),
            caption=(
                f"✅ 导出完成，共 {len(rows)} 条记录。\n"
                f"筛选和显示时区：{settings.business_timezone}（UTC+05:30）"
            ),
        )
    except Exception:
        logger.exception("Export failed for administrator %s", callback.from_user.id)
        await callback.message.answer("❌ 导出失败，请稍后重试或联系超级管理员。")
    finally:
        await state.clear()
        await render_home(callback.message, callback.from_user.id, service, settings)


async def render_administrator_management(
    target: Message, service: BotService, settings: Settings
) -> None:
    administrators = await service.list_admins()
    super_ids = "\n".join(
        f"• <code>{user_id}</code>" for user_id in sorted(settings.super_admin_ids)
    )
    admin_ids = (
        "\n".join(
            (
                f"• <code>{item.telegram_user_id}</code>"
                f"  -  {html.escape(item.display_name)}"
                if item.display_name
                else f"• <code>{item.telegram_user_id}</code>"
            )
            for item in administrators
        )
        or "• 暂无普通管理员"
    )
    await target.answer(
        "<b>管理员管理</b>\n\n"
        f"<b>超级管理员</b>\n{super_ids}\n\n"
        f"<b>普通管理员</b>\n{admin_ids}\n\n",
        reply_markup=administrator_management(
            [(item.telegram_user_id, item.display_name) for item in administrators]
        ),
    )


@router.callback_query(F.data == "admin:admins")
async def manage_administrators(
    callback: CallbackQuery, service: BotService, settings: Settings
) -> None:
    if not is_super_admin(callback.from_user.id, settings):
        await reject_callback(callback)
        return
    await callback.answer()
    await render_administrator_management(callback.message, service, settings)


@router.callback_query(F.data == "admins:add")
async def begin_add_administrator(
    callback: CallbackQuery, state: FSMContext, settings: Settings
) -> None:
    if not is_super_admin(callback.from_user.id, settings):
        await reject_callback(callback)
        return
    await state.set_state(AdministratorStates.waiting_user_id)
    await callback.answer()
    await callback.message.answer(
        "请输入管理员的TG ID和名字，用换行分隔\n\n"
        "格式举例：\n"
        "<pre>123456789\n张三</pre>\n"
        "其中名称可为空，只发送 TG ID 也可以。\n\n"
        "发送 /cancel 取消。"
    )


@router.message(AdministratorStates.waiting_user_id)
async def receive_administrator_id(
    message: Message, state: FSMContext, service: BotService, settings: Settings
) -> None:
    if message.from_user is None or not is_super_admin(message.from_user.id, settings):
        await reject_message(message)
        return
    try:
        new_user_id, display_name = parse_administrator_input(message.text or "")
    except ValueError as exc:
        await message.answer(f"{html.escape(str(exc))}，请重新输入。")
        return
    if new_user_id in settings.super_admin_ids:
        await message.answer("该用户已经是超级管理员。")
        return
    created = await service.add_admin(new_user_id, display_name, message.from_user.id)
    await state.clear()
    if created:
        name_suffix = f"  -  {html.escape(display_name)}" if display_name else ""
        await message.answer(
            f"✅ 已新增管理员 <code>{new_user_id}</code>{name_suffix}。\n"
            "请让该用户私聊机器人并发送 /start。"
        )
    else:
        await message.answer(
            f"管理员 <code>{new_user_id}</code> 已经存在，无需重复新增。"
        )
    await render_home(message, message.from_user.id, service, settings)


@router.callback_query(F.data.startswith("admins:delete:"))
async def begin_delete_administrator(
    callback: CallbackQuery, service: BotService, settings: Settings
) -> None:
    if not is_super_admin(callback.from_user.id, settings):
        await reject_callback(callback)
        return
    try:
        telegram_user_id = int(callback.data.rsplit(":", maxsplit=1)[1])
    except (ValueError, IndexError):
        await callback.answer("管理员 ID 无效", show_alert=True)
        return
    administrator = next(
        (
            item
            for item in await service.list_admins()
            if item.telegram_user_id == telegram_user_id
        ),
        None,
    )
    if administrator is None:
        await callback.answer("该管理员已不存在", show_alert=True)
        return
    name_suffix = (
        f"  -  {html.escape(administrator.display_name)}"
        if administrator.display_name
        else ""
    )
    await callback.answer()
    await callback.message.answer(
        "确定删除以下普通管理员吗？\n\n"
        f"• <code>{administrator.telegram_user_id}</code>{name_suffix}\n\n"
        "删除后，该用户将立即失去机器人管理权限。",
        reply_markup=confirm_delete_administrator(administrator.telegram_user_id),
    )


@router.callback_query(F.data.startswith("admins:delete_confirm:"))
async def confirm_delete_administrator_handler(
    callback: CallbackQuery, service: BotService, settings: Settings
) -> None:
    if not is_super_admin(callback.from_user.id, settings):
        await reject_callback(callback)
        return
    try:
        telegram_user_id = int(callback.data.rsplit(":", maxsplit=1)[1])
    except (ValueError, IndexError):
        await callback.answer("管理员 ID 无效", show_alert=True)
        return
    removed = await service.remove_admin(telegram_user_id, callback.from_user.id)
    await callback.answer(
        "删除成功" if removed else "该管理员已被删除", show_alert=True
    )
    await render_administrator_management(callback.message, service, settings)


@router.callback_query(F.data == "admin:stats")
async def show_stats(
    callback: CallbackQuery, service: BotService, settings: Settings
) -> None:
    if not is_super_admin(callback.from_user.id, settings):
        await reject_callback(callback)
        return
    stats = await service.statistics()
    last_sent = stats["last_sent"]
    if isinstance(last_sent, datetime):
        last_display = (
            ensure_utc(last_sent)
            .astimezone(ZoneInfo(settings.business_timezone))
            .strftime("%Y-%m-%d %H:%M:%S")
        )
    else:
        last_display = "—"
    india_now = utc_now().astimezone(ZoneInfo(settings.business_timezone))
    await callback.answer()
    await callback.message.answer(
        "<b>运行统计</b>\n\n"
        f"累计记录：{stats['total']}\n"
        f"等待/重试回复：{stats['pending']}\n"
        f"回复失败：{stats['failed']}\n"
        f"最后收到照片：{last_display}\n"
        f"当前时间（印度）：{india_now:%Y-%m-%d %H:%M:%S}"
    )


@router.callback_query(F.data == "admin:verify")
async def verify_binding(
    callback: CallbackQuery, bot: Bot, service: BotService, settings: Settings
) -> None:
    if not is_super_admin(callback.from_user.id, settings):
        await reject_callback(callback)
        return
    binding = await service.active_binding()
    if binding is None:
        await callback.answer("当前没有绑定群组", show_alert=True)
        return
    try:
        me = await bot.get_me()
        bot_member = await bot.get_chat_member(binding.chat_id, me.id)
        actor_member = await bot.get_chat_member(binding.chat_id, callback.from_user.id)
        statuses = {ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR}
        valid = bot_member.status in statuses and actor_member.status in statuses
    except (TelegramBadRequest, TelegramForbiddenError):
        valid = False
    await callback.answer(
        "权限验证通过" if valid else "验证失败：请检查机器人和你的群管理员权限",
        show_alert=True,
    )
