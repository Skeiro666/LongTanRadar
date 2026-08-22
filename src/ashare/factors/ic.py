from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def factor_ic_report(
    factor_df: pd.DataFrame,
    factor_cols: list[str],
    *,
    horizons: list[int] | None = None,
    close_col: str = "close",
) -> dict[str, Any]:
    """Pearson / Spearman IC vs forward excess (EW universe) per horizon."""
    from ashare.ml.target import attach_excess_target

    horizons = horizons or [5, 10, 20]
    reports: dict[str, Any] = {}
    for h in horizons:
        data = attach_excess_target(factor_df, horizon=h)
        data = data.dropna(subset=["target"])
        per_factor = {}
        for col in factor_cols:
            if col not in data.columns:
                continue
            ics = []
            for _, g in data.groupby("date"):
                if len(g) < 5:
                    continue
                x = g[col].astype(float)
                y = g["target"].astype(float)
                mask = x.notna() & y.notna()
                if mask.sum() < 5:
                    continue
                pear = float(x[mask].corr(y[mask], method="pearson") or 0)
                spear = float(x[mask].corr(y[mask], method="spearman") or 0)
                ics.append((pear, spear))
            if not ics:
                per_factor[col] = {"status": "insufficient"}
                continue
            pear = pd.Series([a for a, _ in ics])
            spear = pd.Series([b for _, b in ics])
            per_factor[col] = {
                "ic_mean_pearson": float(pear.mean()),
                "ic_mean_spearman": float(spear.mean()),
                "ic_std_spearman": float(spear.std() or 0),
                "icir": float(spear.mean() / (spear.std() + 1e-12)),
                "positive_ic_ratio": float((spear > 0).mean()),
                "n_days": int(len(ics)),
            }
        reports[f"h{h}"] = per_factor
    return reports


def layer_returns(
    factor_df: pd.DataFrame,
    factor: str,
    *,
    horizon: int = 5,
    quantiles: list[float] | None = None,
) -> dict[str, float]:
    from ashare.ml.target import attach_excess_target

    quantiles = quantiles or [0.1, 0.2, 0.8, 0.9]
    data = attach_excess_target(factor_df, horizon=horizon).dropna(subset=["target", factor])
    if data.empty:
        return {}
    data = data.copy()
    data["q"] = data.groupby("date")[factor].rank(pct=True)
    out = {}
    out["top_10"] = float(data.loc[data["q"] >= 0.9, "target"].mean())
    out["top_20"] = float(data.loc[data["q"] >= 0.8, "target"].mean())
    out["bottom_20"] = float(data.loc[data["q"] <= 0.2, "target"].mean())
    out["bottom_10"] = float(data.loc[data["q"] <= 0.1, "target"].mean())
    return out
