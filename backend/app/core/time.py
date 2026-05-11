"""core support code for time."""

from datetime import datetime
from zoneinfo import ZoneInfo


WIB = ZoneInfo("Asia/Jakarta")


def now() -> datetime:
    """Return now for configuration, time, or security helpers."""
    return datetime.now(WIB).replace(tzinfo=None)


def as_wib_aware(value: datetime) -> datetime:
    """Return as wib aware for configuration, time, or security helpers."""
    if value.tzinfo is None:
        return value.replace(tzinfo=WIB)
    return value.astimezone(WIB)


def from_unix_timestamp(value: int) -> datetime:
    """Return from unix timestamp for configuration, time, or security helpers."""
    return datetime.fromtimestamp(value, tz=WIB).replace(tzinfo=None)


def utcnow() -> datetime:
    """Return utcnow for configuration, time, or security helpers."""
    return now()
