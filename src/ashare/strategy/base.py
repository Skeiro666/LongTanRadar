from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date

import pandas as pd

from ashare.models import Bar, OrderIntent, Position, Side
from ashare.symbols import round_lot, to_symbol


@dataclass
class StrategyContext:
    as_of: date
    equity: float
    cash: float
    positions: dict[str, Position]
    bars_today: dict[str, Bar]
    history: dict[str, pd.DataFrame]
    lot_size: int = 100
    rebalance_threshold: float = 0.05
    is_month_end: bool = False

    def tradable(self) -> list[str]:
        out: list[str] = []
        for sym, bar in self.bars_today.items():
            if bar.is_st or bar.is_halt:
                continue
            out.append(sym)
        return out

    def closes(self, symbol: str) -> pd.Series:
        df = self.history.get(to_symbol(symbol))
        if df is None or df.empty:
            return pd.Series(dtype=float)
        return df.set_index("date")["close"].astype(float)

    def position_value(self, symbol: str) -> float:
        pos = self.positions.get(symbol)
        bar = self.bars_today.get(symbol)
        if not pos or not bar:
            return 0.0
        return pos.shares * bar.close

    def current_weights(self) -> dict[str, float]:
        if self.equity <= 0:
            return {}
        return {sym: self.position_value(sym) / self.equity for sym in self.positions}


class Strategy(ABC):
    def on_init(self, ctx: StrategyContext) -> None:
        return None

    @abstractmethod
    def on_date(self, ctx: StrategyContext) -> list[OrderIntent]:
        raise NotImplementedError

    def reset(self) -> None:
        return None


def intents_from_weights(
    ctx: StrategyContext,
    target_weights: dict[str, float],
    reason: str,
) -> list[OrderIntent]:
    """Sell first, then buy. Uses close for sizing; fills happen next session."""
    targets = {to_symbol(k): max(0.0, float(v)) for k, v in target_weights.items() if v and v > 0}
    held = set(ctx.positions.keys()) | set(ctx.bars_today.keys())
    intents: list[OrderIntent] = []

    for sym in sorted(held | set(targets)):
        bar = ctx.bars_today.get(sym)
        if bar is None or bar.close <= 0:
            continue
        pos = ctx.positions.get(sym)
        shares = pos.shares if pos else 0
        current_w = (shares * bar.close) / ctx.equity if ctx.equity > 0 else 0.0
        target_w = targets.get(sym, 0.0)
        if abs(target_w - current_w) < ctx.rebalance_threshold and not (target_w == 0 and shares > 0):
            continue
        target_shares = round_lot(int(ctx.equity * target_w / bar.close), ctx.lot_size)
        delta = target_shares - shares
        if delta <= -ctx.lot_size:
            sell_qty = round_lot(min(shares, -delta), ctx.lot_size)
            if sell_qty >= ctx.lot_size:
                intents.append(
                    OrderIntent(symbol=sym, side=Side.SELL, quantity=sell_qty, reason=reason, reduce_only=True)
                )
        elif delta >= ctx.lot_size:
            intents.append(OrderIntent(symbol=sym, side=Side.BUY, quantity=delta, reason=reason))

    intents.sort(key=lambda x: 0 if x.side == Side.SELL else 1)
    return intents
