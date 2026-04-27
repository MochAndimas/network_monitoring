"""Define module logic for `backend/app/core/time.py`.

This module contains project-specific implementation details.
"""

from datetime import datetime
from zoneinfo import ZoneInfo


WIB = ZoneInfo("Asia/Jakarta")


def now() -> datetime:
    """Return now.

    Returns:
        TODO describe return value.

    """
    return datetime.now(WIB).replace(tzinfo=None)


def as_wib_aware(value: datetime) -> datetime:
    """Return as wib aware.

    Args:
        value: Parameter input untuk routine ini.

    Returns:
        TODO describe return value.

    """
    if value.tzinfo is None:
        return value.replace(tzinfo=WIB)
    return value.astimezone(WIB)


def from_unix_timestamp(value: int) -> datetime:
    """Return from unix timestamp.

    Args:
        value: Parameter input untuk routine ini.

    Returns:
        TODO describe return value.

    """
    return datetime.fromtimestamp(value, tz=WIB).replace(tzinfo=None)


def utcnow() -> datetime:
    """Return utcnow.

    Returns:
        TODO describe return value.

    """
    return now()
