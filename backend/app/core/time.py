from datetime import datetime
from zoneinfo import ZoneInfo


WIB = ZoneInfo("Asia/Jakarta")


def now() -> datetime:
    return datetime.now(WIB).replace(tzinfo=None)


def as_wib_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=WIB)
    return value.astimezone(WIB)


def from_unix_timestamp(value: int) -> datetime:
    return datetime.fromtimestamp(value, tz=WIB).replace(tzinfo=None)


def utcnow() -> datetime:
    return now()
