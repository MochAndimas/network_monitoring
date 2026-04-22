"""Provide application-wide configuration, constants, security, and time helpers for the network monitoring project."""

from datetime import datetime
from zoneinfo import ZoneInfo


WIB = ZoneInfo("Asia/Jakarta")


def now() -> datetime:
    """Handle now for application-wide configuration, constants, security, and time helpers.

    Returns:
        `datetime` result produced by the routine.
    """
    return datetime.now(WIB).replace(tzinfo=None)


def as_wib_aware(value: datetime) -> datetime:
    """Handle as wib aware for application-wide configuration, constants, security, and time helpers.

    Args:
        value: value value used by this routine (type `datetime`).

    Returns:
        `datetime` result produced by the routine.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=WIB)
    return value.astimezone(WIB)


def from_unix_timestamp(value: int) -> datetime:
    """Handle from unix timestamp for application-wide configuration, constants, security, and time helpers.

    Args:
        value: value value used by this routine (type `int`).

    Returns:
        `datetime` result produced by the routine.
    """
    return datetime.fromtimestamp(value, tz=WIB).replace(tzinfo=None)


def utcnow() -> datetime:
    """Handle utcnow for application-wide configuration, constants, security, and time helpers.

    Returns:
        `datetime` result produced by the routine.
    """
    return now()
