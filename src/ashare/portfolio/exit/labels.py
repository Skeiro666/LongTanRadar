from __future__ import annotations

"""Forward return labels — ONLY place that may read future bars (for training/eval)."""

from datetime import date
from typing import Any

import pandas as pd


def _as_date(v: Any) -> date | None:
    if v is None:
        return None
    try:
        return pd.Timestamp(v).date()
    except Exception:  # noqa: BLE001
        return None


def forward_returns(
    bars: pd.DataFrame,
    *,
    signal_date: date | str,
    horizons: list[int] | None = None,
    entry_price: float | None = None,
) -> dict[str, Any]:
    """
    Labels relative to signal_date close (or entry_price).
    Features must use bars with date <= signal_date only.
    """
    horizons = horizons or [1, 5, 10, 20]
    sd = _as_date(signal_date)
    if bars is None or bars.empty or sd is None:
        return {str(h): {"available": False} for h in horizons} | {"available": False}

    df = bars.copy()
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df = df.sort_values("date").reset_index(drop=True)
    idx = df.index[df["date"] == sd]
    if len(idx) == 0:
        # use last bar on or before signal
        prior = df[df["date"] <= sd]
        if prior.empty:
            return {str(h): {"available": False} for h in horizons} | {"available": False}
        i = int(prior.index[-1])
    else:
        i = int(idx[0])

    base = float(entry_price) if entry_price else float(df.loc[i, "close"])
    out: dict[str, Any] = {"available": True, "signal_date": str(df.loc[i, "date"]), "base_price": base}
    for h in horizons:
        j = i + int(h)
        if j >= len(df):
            out[str(h)] = {"available": False, "note": "future_bars_missing"}
            continue
        px = float(df.loc[j, "close"])
        out[str(h)] = {
            "available": True,
            "date": str(df.loc[j, "date"]),
            "price": px,
            "return": (px / base - 1.0) if base else None,
        }
    return out


def assert_features_asof(feature_pack: dict[str, Any], bars: pd.DataFrame, signal_date: date | str) -> bool:
    """Sanity: feature as_of must be <= signal_date; bars used for features must not exceed."""
    sd = _as_date(signal_date)
    fa = _as_date(feature_pack.get("as_of"))
    if sd is None or fa is None:
        return False
    return fa <= sd
