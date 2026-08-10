from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest

from imgbot.timeutils import local_day_bounds, parse_local_range


def test_india_day_bounds_are_converted_to_utc() -> None:
    start, end = local_day_bounds(date(2026, 8, 3), ZoneInfo("Asia/Kolkata"))
    assert start == datetime(2026, 8, 2, 18, 30, tzinfo=UTC)
    assert end == datetime(2026, 8, 3, 18, 30, tzinfo=UTC)


def test_custom_range_includes_the_selected_end_minute() -> None:
    start, end = parse_local_range(
        "2026-08-01 00:00 | 2026-08-03 23:59", ZoneInfo("Asia/Kolkata")
    )
    assert start == datetime(2026, 7, 31, 18, 30, tzinfo=UTC)
    assert end == datetime(2026, 8, 3, 18, 30, tzinfo=UTC)


def test_custom_range_rejects_reverse_order() -> None:
    with pytest.raises(ValueError, match="结束时间"):
        parse_local_range(
            "2026-08-03 10:00 | 2026-08-02 10:00", ZoneInfo("Asia/Kolkata")
        )

