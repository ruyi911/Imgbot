from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo


def utc_now() -> datetime:
    return datetime.now(UTC)


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def local_day_bounds(day: date, timezone: ZoneInfo) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min, timezone)
    end = start + timedelta(days=1)
    return start.astimezone(UTC), end.astimezone(UTC)


def parse_local_range(value: str, timezone: ZoneInfo) -> tuple[datetime, datetime]:
    try:
        left, right = [item.strip() for item in value.split("|", maxsplit=1)]
        start_local = datetime.strptime(left, "%Y-%m-%d %H:%M").replace(tzinfo=timezone)
        end_local = datetime.strptime(right, "%Y-%m-%d %H:%M").replace(tzinfo=timezone)
    except (ValueError, TypeError) as exc:
        raise ValueError("格式应为：YYYY-MM-DD HH:MM | YYYY-MM-DD HH:MM") from exc
    if end_local < start_local:
        raise ValueError("结束时间不能早于开始时间")
    # Inclusive minute in the UI becomes an exclusive next-minute boundary in SQL.
    return start_local.astimezone(UTC), (end_local + timedelta(minutes=1)).astimezone(UTC)

