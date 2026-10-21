from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

CLINIC_TZ = ZoneInfo("Africa/Nairobi")


def future_weekday(hour: int = 9, minute: int = 0, days_ahead: int = 7) -> datetime:
    day = datetime.now(CLINIC_TZ).date() + timedelta(days=days_ahead)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return datetime.combine(day, time(hour, minute), tzinfo=CLINIC_TZ)


def past_datetime(hour: int = 10, minute: int = 0) -> datetime:
    day = datetime.now(CLINIC_TZ).date() - timedelta(days=1)
    return datetime.combine(day, time(hour, minute), tzinfo=CLINIC_TZ)


def soon_datetime() -> datetime:
    now = datetime.now(CLINIC_TZ).replace(second=0, microsecond=0)
    minutes_to_boundary = 30 - (now.minute % 30)
    return now + timedelta(minutes=minutes_to_boundary)


def future_weekend() -> date:
    day = datetime.now(CLINIC_TZ).date() + timedelta(days=7)
    while day.weekday() < 5:
        day += timedelta(days=1)
    return day


def as_datetime(value: str) -> datetime:
    result = datetime.fromisoformat(value)
    return result.replace(tzinfo=ZoneInfo("UTC")) if result.tzinfo is None else result
