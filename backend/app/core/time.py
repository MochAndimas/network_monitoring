"""Define module logic for `backend/app/core/time.py`.

This module contains project-specific implementation details.
"""

from datetime import datetime
from zoneinfo import ZoneInfo


WIB = ZoneInfo("Asia/Jakarta")


def now() -> datetime:
    """Return now.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    return datetime.now(WIB).replace(tzinfo=None)


def as_wib_aware(value: datetime) -> datetime:
    """Return as wib aware.

    Args:
        value: Parameter input untuk routine ini.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    if value.tzinfo is None:
        return value.replace(tzinfo=WIB)
    return value.astimezone(WIB)


def from_unix_timestamp(value: int) -> datetime:
    """Return from unix timestamp.

    Args:
        value: Parameter input untuk routine ini.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    return datetime.fromtimestamp(value, tz=WIB).replace(tzinfo=None)


def utcnow() -> datetime:
    """Return utcnow.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    return now()
