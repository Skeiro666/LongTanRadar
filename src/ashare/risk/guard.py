from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from ashare.models import Order, OrderIntent, Side

logger = logging.getLogger("ashare.risk")


@dataclass
class RiskDecision:
    allowed: bool
    reason: str = ""
    intent: Optional[OrderIntent] = None


class RiskGuard:
    """Name-weight / gross / drawdown / daily-loss. Halt allows sells only."""

    def __init__(
        self,
        max_name_weight: float = 0.20,
        max_gross_weight: float = 0.95,
        max_drawdown: float = 0.20,
        max_daily_loss: float = 0.08,
    ) -> None:
        self.max_name_weight = max_name_weight
        self.max_gross_weight = max_gross_weight
        self.max_drawdown = max_drawdown
        self.max_daily_loss = max_daily_loss
        self.halted = False
        self.halt_reason = ""
        self.peak_equity: Optional[float] = None

    def update_equity(self, equity: float, daily_start_equity: float) -> None:
        if self.peak_equity is None or equity > self.peak_equity:
            self.peak_equity = equity
        if self.peak_equity and self.peak_equity > 0:
            dd = (self.peak_equity - equity) / self.peak_equity
            if dd >= self.max_drawdown:
                self._halt(f"max_drawdown {dd:.2%} >= {self.max_drawdown:.2%}")
        if daily_start_equity > 0:
            day_loss = (daily_start_equity - equity) / daily_start_equity
            if day_loss >= self.max_daily_loss:
                self._halt(f"max_daily_loss {day_loss:.2%} >= {self.max_daily_loss:.2%}")

    def _halt(self, reason: str) -> None:
        if not self.halted:
            logger.error("Risk halt: %s", reason)
        self.halted = True
        self.halt_reason = reason

    def cap_target_weights(self, weights: dict[str, float]) -> dict[str, float]:
        capped: dict[str, float] = {}
        for sym, w in weights.items():
            if w <= 0:
                continue
            capped[sym] = min(float(w), self.max_name_weight)
        gross = sum(capped.values())
        if gross > self.max_gross_weight and gross > 0:
            scale = self.max_gross_weight / gross
            capped = {k: v * scale for k, v in capped.items()}
        return capped

    def filter_intents(self, intents: list[OrderIntent]) -> list[OrderIntent]:
        out: list[OrderIntent] = []
        for it in intents:
            if self.halted and it.side == Side.BUY:
                logger.info("Skip buy %s (halted: %s)", it.symbol, self.halt_reason)
                continue
            out.append(it)
        return out

    def approve_order(self, order: Order, is_reduce: bool) -> RiskDecision:
        if self.halted and not is_reduce:
            return RiskDecision(False, f"halted: {self.halt_reason}")
        return RiskDecision(True, "ok")
