from __future__ import annotations

from typing import Any

import pandas as pd

from ashare.factors.library import enrich_leader_features
from ashare.factors.score import score_candidates
from ashare.strategy.base import Strategy, StrategyContext, intents_from_weights


class LeaderFactorStrategy(Strategy):
    """Backtest: T-day leader factors → T+1 fill. No live events (unknown historically)."""

    def __init__(
        self,
        top_n: int = 5,
        rebalance: str = "week_end",
        max_name_weight: float = 0.25,
        max_gross_weight: float = 0.95,
        rebalance_threshold: float = 0.05,
        cfg: dict[str, Any] | None = None,
        **_: Any,
    ) -> None:
        self.top_n = top_n
        self.rebalance = rebalance
        self.max_name_weight = max_name_weight
        self.max_gross_weight = max_gross_weight
        self.rebalance_threshold = rebalance_threshold
        self.cfg = cfg or {}

    def on_date(self, ctx: StrategyContext) -> list:
        if self.rebalance == "month_end" and not ctx.is_month_end:
            return []
        if self.rebalance == "week_end":
            # Friday or last available day of ISO week in sample
            if ctx.as_of.weekday() != 4 and not ctx.is_month_end:
                return []

        rows: list[dict[str, Any]] = []
        for sym in ctx.tradable():
            bar = ctx.bars_today[sym]
            if bar.limit_up:
                continue
            hist = ctx.history.get(sym)
            if hist is None or hist.empty:
                continue
            h = hist.sort_values("date")
            h = h[pd.to_datetime(h["date"]).dt.date <= ctx.as_of]
            feats = enrich_leader_features(
                h.set_index("date")["close"].astype(float),
                h.set_index("date")["volume"].astype(float) if "volume" in h.columns else None,
                h.set_index("date")["high"].astype(float) if "high" in h.columns else None,
                h.set_index("date")["low"].astype(float) if "low" in h.columns else None,
            )
            if feats is None:
                continue
            # Historical proxy: treat strong mom + volume as "board/event"
            board = 1 if float(feats.get("ret_1") or 0) > 0.09 else 0
            rows.append(
                {
                    "symbol": sym,
                    "feats": feats,
                    "board_count": board,
                    "strong_flag": 1 if float(feats.get("mom_5") or 0) > 0.08 else 0,
                    "profit_gap_score": max(0.0, float(feats.get("mom_20") or 0) * 5),
                    "event_score": float(feats.get("vol_ratio") or 0),
                    "amount": float(h["volume"].iloc[-1]) * float(h["close"].iloc[-1])
                    if "volume" in h.columns
                    else 0.0,
                    "close": float(h["close"].iloc[-1]),
                }
            )
        ranked = score_candidates(rows, self.cfg)
        picked = ranked[: self.top_n]
        if not picked:
            return intents_from_weights(ctx, {}, reason="leader_empty")
        w = min(self.max_name_weight, self.max_gross_weight / max(len(picked), 1))
        weights = {p["symbol"]: w for p in picked}
        ctx.rebalance_threshold = self.rebalance_threshold
        return intents_from_weights(ctx, weights, reason="leader_factor")
