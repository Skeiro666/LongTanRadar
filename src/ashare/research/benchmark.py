from __future__ import annotations

from typing import Any

import pandas as pd


def _forward_return(df: pd.DataFrame, as_of: pd.Timestamp, horizon: int) -> float | None:
    sub = df.copy()
    sub["date"] = pd.to_datetime(sub["date"])
    sub = sub.sort_values("date")
    hist = sub[sub["date"] <= as_of]
    fut = sub[sub["date"] > as_of]
    if hist.empty or len(fut) < horizon:
        return None
    entry = float(hist.iloc[-1]["close"])
    exit_px = float(fut.iloc[horizon - 1]["close"])
    if entry <= 0:
        return None
    return exit_px / entry - 1.0


def equal_weight_benchmark_returns(
    panel: dict[str, pd.DataFrame],
    as_of,
    horizons: list[int] | None = None,
) -> dict[str, Any]:
    """
    Cross-section equal-weight mean forward return (same method as ML target default).
    Used for descriptive excess_return in research attribution — not a tradable index.
    """
    horizons = [int(h) for h in (horizons or [1, 3, 5, 10, 20, 60])]
    as_of_ts = pd.Timestamp(str(as_of)[:10])
    by_h: dict[int, list[float]] = {h: [] for h in horizons}
    used = 0
    for df in panel.values():
        if df is None or df.empty:
            continue
        used += 1
        for h in horizons:
            r = _forward_return(df, as_of_ts, h)
            if r is not None:
                by_h[h].append(r)

    returns: dict[str, float | None] = {}
    for h in horizons:
        vals = by_h[h]
        returns[str(h)] = float(sum(vals) / len(vals)) if vals else None

    return {
        "method": "equal_weight_universe",
        "as_of": str(as_of_ts.date()),
        "n_symbols": used,
        "returns": returns,
    }
