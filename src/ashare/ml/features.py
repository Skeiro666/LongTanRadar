from __future__ import annotations

import numpy as np
import pandas as pd

FEATURE_COLS = [
    "mom_5",
    "mom_20",
    "vol_20",
    "vol_ratio",
    "ma_gap_20",
    "ma_gap_60",
    "ret_1",
    "high_low",
]


def enrich_symbol(df: pd.DataFrame, label_horizon: int = 5) -> pd.DataFrame:
    """Add T-day features and future label (no look-ahead in features)."""
    out = df.copy()
    out["date"] = pd.to_datetime(out["date"])
    out = out.sort_values("date").reset_index(drop=True)
    c = out["close"].astype(float)
    v = out["volume"].astype(float)
    h = out["high"].astype(float)
    lo = out["low"].astype(float)

    out["mom_5"] = c / c.shift(5) - 1.0
    out["mom_20"] = c / c.shift(20) - 1.0
    ret = c.pct_change()
    out["vol_20"] = ret.rolling(20).std()
    vol_ma = v.rolling(20).mean()
    out["vol_ratio"] = v / vol_ma.replace(0, np.nan)
    ma20 = c.rolling(20).mean()
    ma60 = c.rolling(60).mean()
    out["ma_gap_20"] = (c - ma20) / ma20
    out["ma_gap_60"] = (c - ma60) / ma60
    out["ret_1"] = ret
    out["high_low"] = (h - lo) / c.replace(0, np.nan)
    # Label: forward return over label_horizon days (known only after T+h)
    out["label"] = c.shift(-label_horizon) / c - 1.0
    return out


def feature_row_from_closes(
    closes: pd.Series,
    volumes: pd.Series | None = None,
    highs: pd.Series | None = None,
    lows: pd.Series | None = None,
) -> dict[str, float] | None:
    """Build one feature vector from history ending at as_of (inclusive)."""
    if len(closes) < 65:
        return None
    c = closes.astype(float)
    v = volumes.astype(float) if volumes is not None else pd.Series(np.ones(len(c)), index=c.index)
    h = highs.astype(float) if highs is not None else c
    lo = lows.astype(float) if lows is not None else c
    ret = c.pct_change()
    ma20 = float(c.tail(20).mean())
    ma60 = float(c.tail(60).mean())
    last = float(c.iloc[-1])
    if ma20 <= 0 or ma60 <= 0 or last <= 0:
        return None
    vol_ma = float(v.tail(20).mean()) or 1.0
    return {
        "mom_5": float(c.iloc[-1] / c.iloc[-6] - 1.0) if len(c) >= 6 else 0.0,
        "mom_20": float(c.iloc[-1] / c.iloc[-21] - 1.0) if len(c) >= 21 else 0.0,
        "vol_20": float(ret.tail(20).std() or 0.0),
        "vol_ratio": float(v.iloc[-1] / vol_ma),
        "ma_gap_20": (last - ma20) / ma20,
        "ma_gap_60": (last - ma60) / ma60,
        "ret_1": float(ret.iloc[-1] or 0.0),
        "high_low": float((h.iloc[-1] - lo.iloc[-1]) / last),
    }
