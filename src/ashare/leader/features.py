from __future__ import annotations

import math
from typing import Any

import pandas as pd

from ashare.ml.features import feature_row_from_closes
from ashare.strategy.anti_chase import enrich_structure


def _cutoff_ts(as_of: str | None) -> pd.Timestamp | None:
    from ashare.asof import asof_cutoff

    return asof_cutoff(as_of)


def compute_leader_features(
    df: pd.DataFrame,
    *,
    as_of: str | None = None,
) -> dict[str, Any]:
    """T-day and prior bars only — no look-ahead."""
    if df is None or df.empty:
        return {}
    out = df.copy()
    out["date"] = pd.to_datetime(out["date"])
    cut = _cutoff_ts(as_of)
    if cut is not None:
        out = out[pd.to_datetime(out["date"]).dt.normalize() <= cut]
    out = out.sort_values("date").reset_index(drop=True)
    if len(out) < 65:
        return {}
    c = out["close"].astype(float)
    v = out["volume"].astype(float)
    h = out["high"].astype(float)
    lo = out["low"].astype(float)
    feats = feature_row_from_closes(c, v, h, lo) or {}
    feats = enrich_structure(feats, c)
    ma5 = float(c.tail(5).mean()) if len(c) >= 5 else float(c.iloc[-1])
    ma20 = float(c.tail(20).mean())
    ma60 = float(c.tail(60).mean())
    last = float(c.iloc[-1])
    feats["ma_gap_5"] = (last - ma5) / ma5 if ma5 > 0 else 0.0
    feats["distance_to_MA5"] = feats["ma_gap_5"]
    feats["distance_to_MA20"] = feats["ma_gap_20"]
    feats["distance_to_MA60"] = feats["ma_gap_60"]
    feats["mom_10"] = float(c.iloc[-1] / c.iloc[-11] - 1.0) if len(c) >= 11 else 0.0
    feats["ret_5"] = float(c.iloc[-1] / c.iloc[-6] - 1.0) if len(c) >= 6 else 0.0
    feats["ret_10"] = feats["mom_10"]
    feats["ret_20"] = float(feats.get("mom_20") or 0)
    lu = out.get("limit_up")
    ld = out.get("limit_down")
    if lu is not None:
        lu_b = lu.astype(bool)
        feats["limit_up_count_3d"] = float(lu_b.tail(3).sum())
        feats["limit_up_count_5d"] = float(lu_b.tail(5).sum())
        feats["limit_up_count_10d"] = float(lu_b.tail(10).sum())
        feats["limit_up_count_20d"] = float(lu_b.tail(20).sum())
        feats["consecutive_limit_up"] = _consecutive_tail(lu_b)
    else:
        feats["consecutive_limit_up"] = 0.0
        feats["limit_up_count_3d"] = 0.0
        feats["limit_up_count_5d"] = 0.0
        feats["limit_up_count_10d"] = 0.0
        feats["limit_up_count_20d"] = 0.0
    if ld is not None:
        feats["limit_down_count_5d"] = float(ld.astype(bool).tail(5).sum())
    up = (c.pct_change() > 0.001).astype(int)
    feats["consecutive_up_days"] = float(_consecutive_tail(up))
    amt = out.get("amount")
    if amt is not None and len(amt) >= 20:
        a = amt.astype(float)
        mu, sd = float(a.tail(20).mean()), float(a.tail(20).std() or 1.0)
        feats["turnover"] = float(a.iloc[-1])
        feats["turnover_zscore"] = float((a.iloc[-1] - mu) / sd) if sd > 1e-9 else 0.0
    else:
        feats["turnover"] = 0.0
        feats["turnover_zscore"] = 0.0
    vol = v.pct_change()
    feats["volume_zscore"] = float(feats.get("vol_ratio") or 1.0) - 1.0
    v5 = float(vol.tail(5).mean() or 0)
    vprev = float(vol.tail(10).head(5).mean() or 0)
    feats["volume_acceleration"] = v5 - vprev if not (math.isnan(v5) or math.isnan(vprev)) else 0.0
    row = out.iloc[-1]
    feats["limit_up_today"] = bool(row.get("limit_up"))
    feats["limit_down_today"] = bool(row.get("limit_down"))
    feats["high_close_ratio"] = float((h.iloc[-1] - last) / last) if last > 0 else 0.0
    if len(c) >= 20:
        peak = float(c.tail(20).max())
        feats["drawdown_20d"] = float((last - peak) / peak) if peak > 0 else 0.0
    else:
        feats["drawdown_20d"] = 0.0
    feats["gap"] = float(row.get("open", last)) / float(c.iloc[-2]) - 1.0 if len(c) >= 2 and c.iloc[-2] else 0.0
    feats["reversal"] = 1.0 if float(feats.get("ret_1") or 0) < -0.03 and float(feats.get("mom_5") or 0) > 0.05 else 0.0
    return feats


def _consecutive_tail(series: pd.Series) -> int:
    streak = 0
    for x in series.iloc[::-1]:
        if bool(x):
            streak += 1
        else:
            break
    return streak


def limit_up_dates(df: pd.DataFrame, *, as_of: str | None = None) -> dict[str, str | None]:
    if df is None or df.empty or "limit_up" not in df.columns:
        return {"first_limit_up_date": None, "last_limit_up_date": None}
    out = df.copy()
    out["date"] = pd.to_datetime(out["date"])
    cut = _cutoff_ts(as_of)
    if cut is not None:
        out = out[pd.to_datetime(out["date"]).dt.normalize() <= cut]
    lu = out[out["limit_up"].astype(bool)]
    if lu.empty:
        return {"first_limit_up_date": None, "last_limit_up_date": None}
    return {
        "first_limit_up_date": str(lu.iloc[0]["date"].date()),
        "last_limit_up_date": str(lu.iloc[-1]["date"].date()),
    }
