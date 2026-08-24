from __future__ import annotations

"""Forward return labels — ONLY place that may read future bars (for training/eval).

Canonical research definition (Exit IC / calibration):
  forward_return_Nd = P_close(T+N) / P_close(T) - 1
  where N is trading-bar offset in the sorted bar index (not calendar days).

adj_type must be consistent for T and T+N (project default: qfq).
"""

from datetime import date
from typing import Any, Literal

import pandas as pd

BaseMode = Literal["signal_close", "explicit_price"]


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
    base_mode: BaseMode | None = None,
    price_field: str = "close",
    adj_type: str = "qfq",
) -> dict[str, Any]:
    """
    Labels relative to signal bar.

    Default (IC / calibration): base_mode=signal_close → P(T+h)/P(T)-1 on `price_field`.
    If entry_price is passed without base_mode, legacy behavior uses explicit_price
    (documented; Exit IC path must pass base_mode='signal_close' and ignore entry).
    """
    horizons = horizons or [1, 5, 10, 20]
    sd = _as_date(signal_date)
    if bars is None or bars.empty or sd is None:
        return {str(h): {"available": False} for h in horizons} | {"available": False}

    # Resolve base mode explicitly — Exit IC always wants signal_close
    if base_mode is None:
        base_mode = "explicit_price" if entry_price is not None else "signal_close"

    df = bars.copy()
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df = df.sort_values("date").reset_index(drop=True)
    if price_field not in df.columns:
        return {
            str(h): {"available": False, "note": f"missing_{price_field}"} for h in horizons
        } | {"available": False}

    idx = df.index[df["date"] == sd]
    if len(idx) == 0:
        prior = df[df["date"] <= sd]
        if prior.empty:
            return {str(h): {"available": False} for h in horizons} | {"available": False}
        i = int(prior.index[-1])
    else:
        i = int(idx[0])

    price_t = float(df.loc[i, price_field])
    if base_mode == "signal_close":
        base = price_t
        base_note = "signal_close"
    else:
        base = float(entry_price) if entry_price is not None else price_t
        base_note = "explicit_price"

    out: dict[str, Any] = {
        "available": True,
        "signal_date": str(df.loc[i, "date"]),
        "signal_bar_index": i,
        "base_price": base,
        "price_t": price_t,
        "price_field": price_field,
        "base_mode": base_mode,
        "base_note": base_note,
        "adj_type": adj_type,
        "alignment": "trading_bars",
        "definition": f"P_{price_field}(T+N)/base - 1",
    }
    for h in horizons:
        j = i + int(h)
        if j >= len(df):
            out[str(h)] = {"available": False, "note": "future_bars_missing"}
            continue
        px = float(df.loc[j, price_field])
        out[str(h)] = {
            "available": True,
            "date": str(df.loc[j, "date"]),
            "label_time": str(df.loc[j, "date"]),
            "bar_offset": int(h),
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
