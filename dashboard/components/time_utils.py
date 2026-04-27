"""Define module logic for `dashboard/components/time_utils.py`.

This module contains project-specific implementation details.
"""

from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

import pandas as pd


WIB_TIMEZONE = "Asia/Jakarta"
_WIB_ZONE = ZoneInfo(WIB_TIMEZONE)


def to_wib_timestamp(value):
    """Return to wib timestamp.

    Args:
        value: Parameter input untuk routine ini.

    Returns:
        TODO describe return value.

    """
    parsed = pd.to_datetime(value)
    if isinstance(parsed, pd.Series):
        if parsed.dt.tz is None:
            return parsed.dt.tz_localize(WIB_TIMEZONE)
        return parsed.dt.tz_convert(WIB_TIMEZONE)
    if parsed.tzinfo is None:
        return parsed.tz_localize(WIB_TIMEZONE)
    return parsed.tz_convert(WIB_TIMEZONE)


def format_wib_timestamp(value) -> str:
    """Format wib timestamp.

    Args:
        value: Parameter input untuk routine ini.

    Returns:
        TODO describe return value.

    """
    if pd.isna(value):
        return "-"
    return pd.Timestamp(value).strftime("%Y-%m-%d %H:%M:%S WIB")


def wib_date_boundary_to_utc_iso(value, *, end_of_day: bool = False) -> str:
    """Return wib date boundary to utc iso.

    Args:
        value: Parameter input untuk routine ini.
        end_of_day: Parameter input untuk routine ini.

    Returns:
        TODO describe return value.

    """
    boundary_time = time.max if end_of_day else time.min
    localized = datetime.combine(value, boundary_time, tzinfo=_WIB_ZONE)
    return localized.replace(tzinfo=None).isoformat()
