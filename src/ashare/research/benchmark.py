from __future__ import annotations

from typing import Any

import pandas as pd

from ashare.config_loaders import load_yaml_config


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
        "benchmark_available": used > 0,
    }


def csi300_benchmark_returns(
    index_df: pd.DataFrame,
    as_of,
    horizons: list[int] | None = None,
) -> dict[str, Any]:
    """CSI300 (000300) index forward returns — tradable index proxy when data available."""
    horizons = [int(h) for h in (horizons or [1, 3, 5, 10, 20, 60])]
    as_of_ts = pd.Timestamp(str(as_of)[:10])
    if index_df is None or index_df.empty:
        return {
            "method": "csi300",
            "as_of": str(as_of_ts.date()),
            "returns": {str(h): None for h in horizons},
            "benchmark_available": False,
            "note": "csi300_index_unavailable",
        }
    returns: dict[str, float | None] = {}
    for h in horizons:
        returns[str(h)] = _forward_return(index_df, as_of_ts, h)
    wired = any(v is not None for v in returns.values())
    return {
        "method": "csi300",
        "index": "000300",
        "as_of": str(as_of_ts.date()),
        "returns": returns,
        "benchmark_available": wired,
    }


def resolve_benchmark_pack(
    cfg: dict[str, Any],
    panel: dict[str, pd.DataFrame],
    as_of,
    horizons: list[int] | None = None,
) -> dict[str, Any]:
    """
    Pick benchmark per research.tracking.benchmark config.
    Falls back to equal_weight_universe when CSI300 unavailable.
    """
    horizons = [int(h) for h in (horizons or [1, 3, 5, 10, 20, 60])]
    tracking = dict(load_yaml_config(cfg, "research").get("tracking") or {})
    method = str(tracking.get("benchmark") or "equal_weight_universe").lower()
    fallback = str(tracking.get("benchmark_fallback") or "equal_weight_universe").lower()

    if method in {"csi300", "hs300", "000300"}:
        from ashare.data.akshare_source import fetch_csi300_index_bars

        idx = fetch_csi300_index_bars(cfg)
        pack = csi300_benchmark_returns(idx, as_of, horizons=horizons)
        if pack.get("benchmark_available"):
            pack["primary"] = "csi300"
            return pack
        if fallback == "equal_weight_universe":
            fb = equal_weight_benchmark_returns(panel, as_of, horizons=horizons)
            fb["primary"] = "equal_weight_universe"
            fb["fallback_from"] = "csi300_unavailable"
            return fb
        pack["fallback_from"] = "csi300_unavailable"
        return pack

    pack = equal_weight_benchmark_returns(panel, as_of, horizons=horizons)
    pack["primary"] = "equal_weight_universe"
    return pack
