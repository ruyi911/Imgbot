from __future__ import annotations

import csv
import io
from collections.abc import Iterable
from datetime import datetime
from zoneinfo import ZoneInfo

from openpyxl import Workbook

from imgbot.models import Submission
from imgbot.timeutils import ensure_utc

HEADERS = [
    "TG ID",
    "用户昵称",
    "用户名",
    "发送时间（印度）",
    "照片数量",
    "消息ID",
    "群组名称",
    "群组ID",
]


def safe_cell(value: object) -> object:
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def row_values(submission: Submission, timezone: ZoneInfo) -> list[object]:
    sent_at = ensure_utc(submission.sent_at).astimezone(timezone).strftime("%Y-%m-%d %H:%M:%S")
    username = f"@{submission.username_snapshot}" if submission.username_snapshot else ""
    values: list[object] = [
        str(submission.telegram_user_id) if submission.telegram_user_id is not None else "",
        submission.display_name_snapshot,
        username,
        sent_at,
        submission.photo_count,
        submission.primary_message_id,
        submission.chat_title,
        str(submission.chat_id),
    ]
    return [safe_cell(value) for value in values]


def build_csv(submissions: Iterable[Submission], timezone: ZoneInfo) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(HEADERS)
    for submission in submissions:
        writer.writerow(row_values(submission, timezone))
    return ("\ufeff" + stream.getvalue()).encode("utf-8")


def build_xlsx(submissions: Iterable[Submission], timezone: ZoneInfo) -> bytes:
    workbook = Workbook(write_only=True)
    sheet = workbook.create_sheet("消息记录")
    sheet.append(HEADERS)
    for submission in submissions:
        sheet.append(row_values(submission, timezone))
    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


def export_filename(start_utc: datetime, end_utc: datetime, suffix: str) -> str:
    return f"photo_records_{start_utc:%Y%m%d_%H%M}_{end_utc:%Y%m%d_%H%M}.{suffix}"
