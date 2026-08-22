from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def forward_return(close: pd.Series, horizon: int) -> pd.Series:
    c = close.astype(float)
    return c.shift(-horizon) / c - 1.0


def attach_excess_target(
    factor_df: pd.DataFrame,
    *,
    horizon: int = 5,
    benchmark: str = "equal_weight_universe",
    close_col: str = "close",
) -> pd.DataFrame:
    """
    target = stock_fwd_return - benchmark_fwd_return.
    Default benchmark: same-day equal-weight cross-section mean of fwd returns
    (computed after per-symbol fwd return; no future info in features).
    """
    if factor_df.empty:
        return factor_df
    out = factor_df.copy()
    out["date"] = pd.to_datetime(out["date"])
    parts = []
    for sym, g in out.groupby("symbol", sort=False):
        g = g.sort_values("date").copy()
        g["future_return"] = forward_return(g[close_col], horizon)
        g["label_horizon"] = horizon
        parts.append(g)
    out = pd.concat(parts, ignore_index=True)
    if benchmark == "equal_weight_universe":
        out["benchmark_return"] = out.groupby("date")["future_return"].transform("mean")
    else:
        out["benchmark_return"] = 0.0
    out["target"] = out["future_return"] - out["benchmark_return"]
    out["feature_asof"] = out["date"]
    out["label_asof"] = out["date"] + pd.to_timedelta(horizon, unit="D")  # calendar proxy; trading check in leakage
    return out
