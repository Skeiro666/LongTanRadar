from __future__ import annotations

from ashare.models import OrderIntent
from ashare.strategy.base import Strategy, StrategyContext, intents_from_weights


class DualMAStrategy(Strategy):
    """Equal-weight longs where fast MA > slow MA. Filters ST / halt via context."""

    def __init__(
        self,
        fast: int = 10,
        slow: int = 30,
        max_positions: int = 8,
        rebalance_threshold: float = 0.05,
        max_name_weight: float = 0.20,
        max_gross_weight: float = 0.95,
    ) -> None:
        self.fast = int(fast)
        self.slow = int(slow)
        self.max_positions = int(max_positions)
        self.rebalance_threshold = float(rebalance_threshold)
        self.max_name_weight = float(max_name_weight)
        self.max_gross_weight = float(max_gross_weight)

    def on_date(self, ctx: StrategyContext) -> list[OrderIntent]:
        ctx.rebalance_threshold = self.rebalance_threshold
        scored: list[tuple[str, float]] = []
        need = self.slow + 1
        for sym in ctx.tradable():
            closes = ctx.closes(sym)
            if len(closes) < need:
                continue
            fast_ma = float(closes.tail(self.fast).mean())
            slow_ma = float(closes.tail(self.slow).mean())
            if fast_ma > slow_ma and slow_ma > 0:
                scored.append((sym, fast_ma / slow_ma))
        scored.sort(key=lambda x: x[1], reverse=True)
        picked = [s for s, _ in scored[: self.max_positions]]
        if not picked:
            return intents_from_weights(ctx, {}, reason="dual_ma_flat")
        raw = 1.0 / len(picked)
        w = min(raw, self.max_name_weight)
        weights = {s: w for s in picked}
        gross = sum(weights.values())
        if gross > self.max_gross_weight:
            scale = self.max_gross_weight / gross
            weights = {k: v * scale for k, v in weights.items()}
        return intents_from_weights(ctx, weights, reason="dual_ma")
