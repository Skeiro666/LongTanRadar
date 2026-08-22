from __future__ import annotations

from typing import Iterable

import numpy as np
import pandas as pd


def winsorize_series(s: pd.Series, low: float = 0.01, high: float = 0.99) -> pd.Series:
    if s.dropna().empty:
        return s
    lo = s.quantile(low)
    hi = s.quantile(high)
    return s.clip(lo, hi)


def cross_section_zscore(s: pd.Series) -> pd.Series:
    v = s.astype(float)
    std = float(v.std(skipna=True) or 0.0)
    if std < 1e-12:
        return pd.Series(0.0, index=s.index)
    mean = float(v.mean(skipna=True) or 0.0)
    return (v - mean) / std


def cross_section_percentile(s: pd.Series) -> pd.Series:
    return s.rank(pct=True, method="average")


def normalize_cross_section(
    frame: pd.DataFrame,
    cols: Iterable[str],
    *,
    method: str = "winsorize_zscore",
    winsorize_low: float = 0.01,
    winsorize_high: float = 0.99,
) -> pd.DataFrame:
    """Per-date cross-sectional normalize. frame must have column `date`."""
    out = frame.copy()
    cols = [c for c in cols if c in out.columns]
    if not cols:
        return out

    def _one(g: pd.DataFrame) -> pd.DataFrame:
        g = g.copy()
        for c in cols:
            s = g[c].astype(float)
            if method == "percentile":
                g[c] = cross_section_percentile(s)
            else:
                w = winsorize_series(s, winsorize_low, winsorize_high)
                g[c] = cross_section_zscore(w)
        return g

    parts = [_one(g) for _, g in out.groupby("date", sort=False)]
    if not parts:
        return out
    return pd.concat(parts, ignore_index=True)


def category_score(z_row: dict[str, float], factor_names: list[str]) -> float:
    vals = [float(z_row[n]) for n in factor_names if n in z_row and np.isfinite(z_row[n])]
    if not vals:
        return 0.0
    return float(np.nanmean(vals))
