from __future__ import annotations

import pandas as pd


WIB_TIMEZONE = "Asia/Jakarta"


def to_wib_timestamp(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, utc=True).dt.tz_convert(WIB_TIMEZONE)


def format_wib_timestamp(value) -> str:
    if pd.isna(value):
        return "-"
    return pd.Timestamp(value).strftime("%Y-%m-%d %H:%M:%S WIB")
