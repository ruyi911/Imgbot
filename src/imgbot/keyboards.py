from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def admin_menu(is_bound: bool, *, is_super_admin: bool) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(text="🖼 首页媒体", callback_data="admin:start_media"),
            InlineKeyboardButton(text="📝 首页文案", callback_data="admin:start_text"),
            InlineKeyboardButton(
                text="🔗 首页按钮", callback_data="admin:start_buttons"
            ),
        ]
    ]
    if is_bound:
        rows.extend(
            [
                [
                    InlineKeyboardButton(
                        text="📝 回复文案", callback_data="admin:template"
                    ),
                    InlineKeyboardButton(
                        text="🔗 回复按钮", callback_data="admin:buttons"
                    ),
                ],
                [
                    InlineKeyboardButton(
                        text="📤 导出数据", callback_data="admin:export"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="⛓️‍💥 解绑群组", callback_data="admin:unbind"
                    )
                ],
            ]
        )
        if is_super_admin:
            rows.insert(
                -1,
                [
                    InlineKeyboardButton(
                        text="📊 运行统计", callback_data="admin:stats"
                    ),
                    InlineKeyboardButton(
                        text="🔍 重新验证权限", callback_data="admin:verify"
                    ),
                ],
            )
    else:
        rows.append(
            [InlineKeyboardButton(text="🔗 绑定群组", callback_data="admin:bind")]
        )
    if is_super_admin:
        rows.append(
            [InlineKeyboardButton(text="👥 管理员管理", callback_data="admin:admins")]
        )
    rows.append([InlineKeyboardButton(text="🔄 刷新", callback_data="admin:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def confirm_binding() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ 确认绑定", callback_data="bind:confirm"),
                InlineKeyboardButton(text="取消", callback_data="bind:cancel"),
            ]
        ]
    )


def confirm_unbind() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⚠️ 确认解除", callback_data="unbind:confirm"
                ),
                InlineKeyboardButton(text="取消", callback_data="admin:home"),
            ]
        ]
    )


def administrator_management(
    administrators: list[tuple[int, str | None]],
) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text="➕ 新增管理员", callback_data="admins:add")]]
    rows.extend(
        [
            InlineKeyboardButton(
                text=f"🗑 删除 {user_id}{f' - {name[:24]}' if name else ''}",
                callback_data=f"admins:delete:{user_id}",
            )
        ]
        for user_id, name in administrators
    )
    rows.append([InlineKeyboardButton(text="返回首页", callback_data="admin:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def confirm_delete_administrator(telegram_user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⚠️ 确认删除",
                    callback_data=f"admins:delete_confirm:{telegram_user_id}",
                ),
                InlineKeyboardButton(text="取消", callback_data="admin:admins"),
            ]
        ]
    )


def export_ranges() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="今天", callback_data="export:today"),
                InlineKeyboardButton(text="昨天", callback_data="export:yesterday"),
            ],
            [InlineKeyboardButton(text="最近 7 天", callback_data="export:7days")],
            [InlineKeyboardButton(text="自定义时间", callback_data="export:custom")],
            [InlineKeyboardButton(text="返回", callback_data="admin:home")],
        ]
    )


def export_formats() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="XLSX", callback_data="exportfmt:xlsx"),
                InlineKeyboardButton(text="CSV", callback_data="exportfmt:csv"),
            ],
            [InlineKeyboardButton(text="取消", callback_data="admin:home")],
        ]
    )
