"""As-of helpers for daily-bar filters (no tz-aware vs naive compare bugs)."""
from __future__ import annotations

from typing import Any

import pandas as pd


def asof_cutoff(as_of: Any | None) -> pd.Timestamp | None:
    """
    Normalize any as_of (date / datetime / ISO str / Timestamp) to tz-naive midnight.
    Safe to compare with parquet daily `date` columns (datetime64[ns]).
    """
    if as_of is None or as_of == "":
        return None
    try:
        ts = pd.Timestamp(as_of)
    except Exception:  # noqa: BLE001
        return None
    if pd.isna(ts):
        return None
    if getattr(ts, "tz", None) is not None:
        ts = ts.tz_convert(None)
    return ts.normalize()


def mask_on_or_before(dates: pd.Series, as_of: Any | None) -> pd.Series:
    """Boolean mask: dates <= as_of (day resolution, tz-safe)."""
    cut = asof_cutoff(as_of)
    series = pd.to_datetime(dates)
    if cut is None:
        return pd.Series(True, index=series.index)
    # Drop tz on series if present so compare never mixes aware/naive.
    if getattr(series.dt, "tz", None) is not None:
        series = series.dt.tz_convert(None)
    return series.dt.normalize() <= cut
