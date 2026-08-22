from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

from ashare.config_loaders import load_yaml_config
from ashare.factors.catalog import FactorCatalog, catalog_from_yaml
from ashare.factors.normalize import category_score, normalize_cross_section

logger = logging.getLogger("ashare.factors.engine")

VALUE_AVAILABLE = False
QUALITY_AVAILABLE = False
SECTOR_RS_AVAILABLE = False


def _safe_div(a: pd.Series, b: pd.Series) -> pd.Series:
    return a / b.replace(0, np.nan)


def compute_symbol_factors(df: pd.DataFrame) -> pd.DataFrame:
    """Vectorized per-symbol factors from OHLCV. No look-ahead."""
    out = df.copy()
    out["date"] = pd.to_datetime(out["date"])
    out = out.sort_values("date").reset_index(drop=True)
    c = out["close"].astype(float)
    h = out["high"].astype(float) if "high" in out.columns else c
    lo = out["low"].astype(float) if "low" in out.columns else c
    v = out["volume"].astype(float) if "volume" in out.columns else pd.Series(1.0, index=out.index)
    amt = out["amount"].astype(float) if "amount" in out.columns else v * c
    ret = c.pct_change()

    out["momentum_5d"] = c / c.shift(5) - 1.0
    out["momentum_10d"] = c / c.shift(10) - 1.0
    out["momentum_20d"] = c / c.shift(20) - 1.0
    out["momentum_60d"] = c / c.shift(60) - 1.0
    out["momentum_120d"] = c / c.shift(120) - 1.0
    out["momentum_acceleration"] = out["momentum_10d"] - out["momentum_60d"]
    out["positive_return_ratio_20d"] = (ret > 0).astype(float).rolling(20).mean()

    ma5 = c.rolling(5).mean()
    ma20 = c.rolling(20).mean()
    ma60 = c.rolling(60).mean()
    out["trend_consistency_20d"] = (c > ma20).astype(float).rolling(20).mean()
    out["distance_to_ma5"] = _safe_div(c, ma5) - 1.0
    out["distance_to_ma20"] = _safe_div(c, ma20) - 1.0
    out["distance_to_ma60"] = _safe_div(c, ma60) - 1.0
    out["breakout_20d"] = _safe_div(c, h.rolling(20).max()) - 1.0
    out["breakout_60d"] = _safe_div(c, h.rolling(60).max()) - 1.0
    rmin = c.rolling(60).min()
    rmax = c.rolling(60).max()
    out["high_position_60d"] = _safe_div(c - rmin, rmax - rmin)
    out["ma_alignment"] = ((ma5 > ma20) & (ma20 > ma60)).astype(float)
    out["trend_strength"] = np.where(
        out["ma_alignment"] > 0,
        (out["distance_to_ma20"].fillna(0) + out["distance_to_ma60"].fillna(0)) / 2.0,
        np.minimum(out["distance_to_ma20"].fillna(0), 0.0),
    )

    out["volume_ratio_5d"] = _safe_div(v, v.rolling(5).mean())
    out["volume_ratio_20d"] = _safe_div(v, v.rolling(20).mean())
    out["amount_growth_20d"] = amt / amt.shift(20) - 1.0
    # turnover proxy without float shares
    out["turnover_rate"] = _safe_div(amt, c)

    out["volatility_10d"] = ret.rolling(10).std()
    out["volatility_20d"] = ret.rolling(20).std()
    out["volatility_60d"] = ret.rolling(60).std()
    prev_c = c.shift(1)
    tr = pd.concat([(h - lo).abs(), (h - prev_c).abs(), (lo - prev_c).abs()], axis=1).max(axis=1)
    out["atr_14"] = tr.rolling(14).mean()
    out["volatility_ratio"] = _safe_div(out["volatility_10d"], out["volatility_60d"])

    # consecutive rise days
    up = (ret > 0).astype(int)
    streak = up.copy()
    for i in range(1, len(streak)):
        streak.iloc[i] = streak.iloc[i - 1] + 1 if up.iloc[i] else 0
    out["consecutive_rise_days"] = streak.astype(float)

    if "limit_up" in out.columns:
        lu = out["limit_up"].astype(bool).astype(float)
        out["limit_up_count_20d"] = lu.rolling(20).sum()
        out["limit_up_count_60d"] = lu.rolling(60).sum()
    else:
        out["limit_up_count_20d"] = np.nan
        out["limit_up_count_60d"] = np.nan

    # unavailable stubs — explicit NaN, never fake PE
    for col in (
        "sector_relative_strength_5d",
        "sector_relative_strength_20d",
        "sector_relative_strength_60d",
        "sector_rank_5d",
        "sector_rank_20d",
        "sector_rank_60d",
        "pe",
        "pb",
        "ps",
        "pe_percentile",
        "pb_percentile",
        "roe",
        "roa",
        "revenue_growth",
        "profit_growth",
        "debt_ratio",
    ):
        out[col] = np.nan

    out["_amount"] = amt
    out["_ret_5"] = out["momentum_5d"]
    out["_ret_20"] = out["momentum_20d"]
    out["_ret_60"] = out["momentum_60d"]
    return out


def _add_cross_section_market_rs(panel_df: pd.DataFrame) -> pd.DataFrame:
    """Equal-weight universe return as market proxy until index series exists."""
    if panel_df.empty:
        return panel_df
    out = panel_df.copy()
    for col, src in (
        ("market_relative_strength_5d", "_ret_5"),
        ("market_relative_strength_20d", "_ret_20"),
        ("market_relative_strength_60d", "_ret_60"),
    ):
        mkt = out.groupby("date")[src].transform("mean")
        out[col] = out[src] - mkt
    out["market_rank_20d"] = out.groupby("date")["_ret_20"].rank(pct=True)
    out["amount_rank_20d"] = out.groupby("date")["_amount"].rank(pct=True)
    out["turnover_percentile_20d"] = out.groupby("date")["turnover_rate"].rank(pct=True)
    # liquidity_score: amount rank + inverse short-term vol noise
    vol_z = out.groupby("date")["volatility_20d"].transform(lambda s: (s - s.mean()) / (s.std() + 1e-12))
    out["liquidity_score"] = out["amount_rank_20d"].fillna(0) - 0.25 * vol_z.fillna(0).clip(-2, 2)
    return out


class FactorEngine:
    """Compute / normalize factor library. Does not fabricate fundamentals."""

    def __init__(self, cfg: dict[str, Any] | None = None) -> None:
        self.cfg = cfg or {}
        raw = load_yaml_config(self.cfg, "factors")
        self.catalog: FactorCatalog = catalog_from_yaml(raw)
        self.value_available = VALUE_AVAILABLE
        self.quality_available = QUALITY_AVAILABLE
        self.sector_rs_available = SECTOR_RS_AVAILABLE

    def compute_panel(self, panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
        frames: list[pd.DataFrame] = []
        for sym, df in panel.items():
            if df is None or df.empty:
                continue
            enriched = compute_symbol_factors(df)
            enriched["symbol"] = sym
            frames.append(enriched)
        if not frames:
            return pd.DataFrame()
        data = pd.concat(frames, ignore_index=True)
        data = _add_cross_section_market_rs(data)
        return data

    def normalize(self, factor_df: pd.DataFrame) -> pd.DataFrame:
        cols = self.catalog.available_names()
        norm = self.catalog.normalization
        return normalize_cross_section(
            factor_df,
            cols,
            method=str(norm.get("method") or "winsorize_zscore"),
            winsorize_low=float(norm.get("winsorize_low", 0.01)),
            winsorize_high=float(norm.get("winsorize_high", 0.99)),
        )

    def leader_scores(self, z_df: pd.DataFrame) -> pd.DataFrame:
        """Category composites + Leader Score from config weights."""
        out = z_df.copy()
        cats = {
            "momentum": self.catalog.by_category("momentum"),
            "relative_strength": [n for n in self.catalog.by_category("relative_strength") if "sector" not in n],
            "liquidity": self.catalog.by_category("volume_liquidity"),
            "breakout": self.catalog.by_category("breakout_trend"),
            "attention": self.catalog.by_category("attention"),
            "quality": self.catalog.by_category("quality"),
            "value": self.catalog.by_category("value"),
        }
        for cat, names in cats.items():
            present = [n for n in names if n in out.columns]
            if not present:
                out[f"score_{cat}"] = 0.0
                continue
            out[f"score_{cat}"] = out[present].astype(float).mean(axis=1, skipna=True).fillna(0.0)

        w = self.catalog.leader_weights
        out["leader_score"] = (
            float(w.get("momentum", 0)) * out["score_momentum"]
            + float(w.get("relative_strength", 0)) * out["score_relative_strength"]
            + float(w.get("liquidity", 0)) * out["score_liquidity"]
            + float(w.get("breakout", 0)) * out["score_breakout"]
            + float(w.get("attention", 0)) * out["score_attention"]
            + float(w.get("quality", 0)) * out["score_quality"]
            + float(w.get("value", 0)) * out["score_value"]
        )
        return out

    def asof_rows(self, panel: dict[str, pd.DataFrame], as_of: Any | None = None) -> list[dict[str, Any]]:
        raw = self.compute_panel(panel)
        if raw.empty:
            return []
        z = self.normalize(raw)
        scored = self.leader_scores(z)
        if as_of is not None:
            scored = scored[pd.to_datetime(scored["date"]) <= pd.Timestamp(as_of)]
        # latest row per symbol
        scored = scored.sort_values("date")
        last = scored.groupby("symbol", as_index=False).tail(1)
        rows: list[dict[str, Any]] = []
        avail = self.catalog.available_names()
        for _, r in last.iterrows():
            factors = {n: (None if pd.isna(r.get(n)) else float(r[n])) for n in avail if n in r}
            rows.append(
                {
                    "symbol": r["symbol"],
                    "date": pd.Timestamp(r["date"]).date().isoformat(),
                    "leader_score": float(r.get("leader_score") or 0),
                    "score_momentum": float(r.get("score_momentum") or 0),
                    "score_relative_strength": float(r.get("score_relative_strength") or 0),
                    "score_liquidity": float(r.get("score_liquidity") or 0),
                    "score_breakout": float(r.get("score_breakout") or 0),
                    "score_attention": float(r.get("score_attention") or 0),
                    "score_quality": float(r.get("score_quality") or 0),
                    "score_value": float(r.get("score_value") or 0),
                    "factors": factors,
                    "value_available": self.value_available,
                    "quality_available": self.quality_available,
                    "sector_rs_available": self.sector_rs_available,
                }
            )
        rows.sort(key=lambda x: x["leader_score"], reverse=True)
        return rows
