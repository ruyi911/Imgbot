from datetime import UTC, datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from imgbot.exporter import HEADERS, build_csv, row_values, safe_cell


def make_submission() -> SimpleNamespace:
    return SimpleNamespace(
        chat_title="测试群",
        chat_id=-100123,
        sent_at=datetime(2026, 8, 3, 6, 30, tzinfo=UTC),
        telegram_user_id=12345,
        display_name_snapshot="=2+2",
        username_snapshot="tester",
        primary_message_id=88,
        photo_count=1,
    )


def test_safe_cell_blocks_excel_formula_prefixes() -> None:
    assert safe_cell("=2+2") == "'=2+2"
    assert safe_cell("normal") == "normal"


def test_export_uses_india_time() -> None:
    row = row_values(make_submission(), ZoneInfo("Asia/Kolkata"))
    assert row == [
        "12345",
        "'=2+2",
        "'@tester",
        "2026-08-03 12:00:00",
        1,
        88,
        "测试群",
        "'-100123",
    ]


def test_headers_have_exact_requested_fields_and_order() -> None:
    assert HEADERS == [
        "TG ID",
        "用户昵称",
        "用户名",
        "发送时间（印度）",
        "照片数量",
        "消息ID",
        "群组名称",
        "群组ID",
    ]


def test_csv_has_utf8_bom_and_headers() -> None:
    payload = build_csv([make_submission()], ZoneInfo("Asia/Kolkata"))
    assert payload.startswith(b"\xef\xbb\xbf")
    decoded = payload.decode("utf-8-sig")
    assert "发送时间（印度）" in decoded
    assert "'=2+2" in decoded
    assert len(decoded.splitlines()[0].split(",")) == 8
    assert len(decoded.splitlines()[1].split(",")) == 8
