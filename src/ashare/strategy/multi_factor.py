from __future__ import annotations

import numpy as np

from ashare.models import OrderIntent
from ashare.strategy.base import Strategy, StrategyContext, intents_from_weights


def _zscore(values: dict[str, float]) -> dict[str, float]:
    if not values:
        return {}
    arr = np.array(list(values.values()), dtype=float)
    std = float(arr.std())
    mean = float(arr.mean())
    if std < 1e-12:
        return {k: 0.0 for k in values}
    return {k: (v - mean) / std for k, v in values.items()}


class MultiFactorStrategy(Strategy):
    """Monthly cross-section: momentum + low-vol + cheap vs MA (value proxy)."""

    def __init__(
        self,
        lookback_mom: int = 20,
        lookback_vol: int = 20,
        lookback_value: int = 60,
        top_n: int = 5,
        w_mom: float = 0.4,
        w_vol: float = 0.3,
        w_value: float = 0.3,
        max_name_weight: float = 0.20,
        max_gross_weight: float = 0.95,
        rebalance: str = "month_end",
        rebalance_threshold: float = 0.05,
    ) -> None:
        self.lookback_mom = int(lookback_mom)
        self.lookback_vol = int(lookback_vol)
        self.lookback_value = int(lookback_value)
        self.top_n = int(top_n)
        self.w_mom = float(w_mom)
        self.w_vol = float(w_vol)
        self.w_value = float(w_value)
        self.max_name_weight = float(max_name_weight)
        self.max_gross_weight = float(max_gross_weight)
        self.rebalance = rebalance
        self.rebalance_threshold = float(rebalance_threshold)

    def on_date(self, ctx: StrategyContext) -> list[OrderIntent]:
        ctx.rebalance_threshold = self.rebalance_threshold
        if self.rebalance == "month_end" and not ctx.is_month_end:
            return []

        mom: dict[str, float] = {}
        vol: dict[str, float] = {}
        val: dict[str, float] = {}
        need = max(self.lookback_mom, self.lookback_vol, self.lookback_value) + 2
        for sym in ctx.tradable():
            closes = ctx.closes(sym)
            if len(closes) < need:
                continue
            ret = closes.pct_change().dropna()
            if len(ret) < self.lookback_vol:
                continue
            mom[sym] = float(closes.iloc[-1] / closes.iloc[-self.lookback_mom] - 1.0)
            vol[sym] = float(ret.tail(self.lookback_vol).std())
            ma = float(closes.tail(self.lookback_value).mean())
            last = float(closes.iloc[-1])
            val[sym] = (ma - last) / ma if ma > 0 else 0.0

        z_m = _zscore(mom)
        z_v = {k: -vv for k, vv in _zscore(vol).items()}
        z_val = _zscore(val)
        names = set(z_m) & set(z_v) & set(z_val)
        scores = {
            s: self.w_mom * z_m[s] + self.w_vol * z_v[s] + self.w_value * z_val[s] for s in names
        }
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        picked = [s for s, _ in ranked[: self.top_n]]
        if not picked:
            return intents_from_weights(ctx, {}, reason="multi_factor_flat")
        raw = 1.0 / len(picked)
        w = min(raw, self.max_name_weight)
        weights = {s: w for s in picked}
        gross = sum(weights.values())
        if gross > self.max_gross_weight:
            scale = self.max_gross_weight / gross
            weights = {k: v * scale for k, v in weights.items()}
        return intents_from_weights(ctx, weights, reason="multi_factor")
