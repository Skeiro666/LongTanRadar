from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any, Optional

from ashare.account.ledger import Ledger
from ashare.models import Bar, Fill, Order, Position, Side
from ashare.symbols import round_lot

logger = logging.getLogger("ashare.brokers.paper")


class PaperBroker:
    """Local A-share cash account: T+1, lots, fees, halt / limit-up matching."""

    def __init__(
        self,
        initial_balance: float = 1_000_000.0,
        commission_rate: float = 0.00025,
        min_commission: float = 5.0,
        stamp_tax_rate: float = 0.0005,
        transfer_fee_rate: float = 0.00001,
        slippage_bps: float = 5.0,
        lot_size: int = 100,
        state_file: str = "data/paper_state.json",
        reset_on_start: bool = False,
        persist: bool = True,
    ) -> None:
        self.initial_balance = float(initial_balance)
        self.commission_rate = float(commission_rate)
        self.min_commission = float(min_commission)
        self.stamp_tax_rate = float(stamp_tax_rate)
        self.transfer_fee_rate = float(transfer_fee_rate)
        self.slippage_bps = float(slippage_bps)
        self.lot_size = int(lot_size)
        self.persist_enabled = persist
        self.ledger = Ledger(state_file)

        self.cash = self.initial_balance
        self.realized_pnl = 0.0
        self.positions: dict[str, Position] = {}
        self.peak_equity = self.initial_balance
        self.daily_start_equity = self.initial_balance
        self.last_date: Optional[str] = None
        self.pending: list[dict[str, Any]] = []

        if persist and not reset_on_start:
            self._restore()
        elif persist:
            self._persist()

    def _restore(self) -> None:
        state = self.ledger.load()
        if not state:
            self._persist()
            return
        self.cash = float(state.get("cash", self.initial_balance))
        self.realized_pnl = float(state.get("realized_pnl", 0.0))
        self.peak_equity = float(state.get("peak_equity", self.cash))
        self.daily_start_equity = float(state.get("daily_start_equity", self.cash))
        self.last_date = state.get("last_date")
        self.pending = list(state.get("pending", []))
        self.positions = {}
        for raw in state.get("positions", []):
            pos = Position(
                symbol=raw["symbol"],
                shares=int(raw.get("shares", 0)),
                available=int(raw.get("available", 0)),
                cost_price=float(raw.get("cost_price", 0.0)),
            )
            if pos.shares > 0:
                self.positions[pos.symbol] = pos
        logger.info(
            "Paper restored cash=%.2f positions=%d last_date=%s",
            self.cash,
            len(self.positions),
            self.last_date,
        )

    def _persist(self, marks: Optional[dict[str, float]] = None) -> None:
        if not self.persist_enabled:
            return
        equity = self.get_equity(marks or {})
        state = {
            "cash": self.cash,
            "equity": equity,
            "realized_pnl": self.realized_pnl,
            "peak_equity": self.peak_equity,
            "daily_start_equity": self.daily_start_equity,
            "last_date": self.last_date,
            "pending": self.pending,
            "positions": [
                {
                    "symbol": p.symbol,
                    "shares": p.shares,
                    "available": p.available,
                    "cost_price": p.cost_price,
                }
                for p in self.positions.values()
            ],
        }
        self.ledger.save(state)

    def session_open(self, as_of: date, equity_mark: Optional[dict[str, float]] = None) -> None:
        """Unlock T+1 shares at the start of a new trading day."""
        day = as_of.isoformat()
        if self.last_date != day:
            if equity_mark is not None:
                self.daily_start_equity = self.get_equity(equity_mark)
            for pos in self.positions.values():
                pos.available = pos.shares
        self.last_date = day

    def get_position(self, symbol: str) -> Position:
        return self.positions.get(symbol, Position(symbol=symbol))

    def market_value(self, marks: dict[str, float]) -> float:
        total = 0.0
        for sym, pos in self.positions.items():
            px = marks.get(sym, pos.cost_price)
            total += pos.shares * px
        return total

    def get_equity(self, marks: dict[str, float]) -> float:
        equity = self.cash + self.market_value(marks)
        if equity > self.peak_equity:
            self.peak_equity = equity
        return equity

    def _apply_slippage(self, side: Side, price: float) -> float:
        slip = self.slippage_bps / 10_000.0
        if side == Side.BUY:
            return price * (1.0 + slip)
        return price * (1.0 - slip)

    def _fee(self, side: Side, amount: float) -> float:
        commission = max(amount * self.commission_rate, self.min_commission)
        transfer = amount * self.transfer_fee_rate
        stamp = amount * self.stamp_tax_rate if side == Side.SELL else 0.0
        return commission + transfer + stamp

    def execute(self, order: Order, bar: Bar, fill_price: float) -> Fill:
        ts = datetime.combine(bar.date, datetime.min.time()).replace(tzinfo=timezone.utc)
        qty = round_lot(int(order.quantity), self.lot_size)
        if qty <= 0:
            return Fill(
                symbol=order.symbol,
                side=order.side,
                quantity=0,
                price=fill_price,
                fee=0.0,
                timestamp=ts,
                reason=order.reason,
                rejected=True,
                reject_reason="lot_size",
            )

        if bar.is_halt or bar.volume <= 0:
            return self._reject(order, fill_price, ts, "halt")
        if order.side == Side.BUY and (bar.limit_up or bar.is_st):
            why = "limit_up" if bar.limit_up else "st"
            return self._reject(order, fill_price, ts, why)
        if order.side == Side.SELL and bar.limit_down:
            return self._reject(order, fill_price, ts, "limit_down")

        px = self._apply_slippage(order.side, fill_price)
        if px <= 0:
            return self._reject(order, fill_price, ts, "bad_price")

        if order.side == Side.SELL:
            pos = self.positions.get(order.symbol)
            if not pos or pos.available < qty:
                avail = pos.available if pos else 0
                return self._reject(order, px, ts, f"t+1_or_qty available={avail}")
            amount = px * qty
            fee = self._fee(Side.SELL, amount)
            realized = (px - pos.cost_price) * qty
            pos.shares -= qty
            pos.available -= qty
            if pos.shares <= 0:
                self.positions.pop(order.symbol, None)
            self.cash += amount - fee
            self.realized_pnl += realized - fee
            return self._fill(order, qty, px, fee, ts, realized)

        amount = px * qty
        fee = self._fee(Side.BUY, amount)
        total = amount + fee
        if total > self.cash + 1e-6:
            affordable = int((self.cash / (px * (1 + self.commission_rate + self.transfer_fee_rate))) // self.lot_size * self.lot_size)
            if affordable < self.lot_size:
                return self._reject(order, px, ts, "insufficient_cash")
            qty = affordable
            amount = px * qty
            fee = self._fee(Side.BUY, amount)
            total = amount + fee
        self.cash -= total
        pos = self.positions.get(order.symbol)
        if pos is None:
            self.positions[order.symbol] = Position(
                symbol=order.symbol,
                shares=qty,
                available=0,
                cost_price=px,
            )
        else:
            new_shares = pos.shares + qty
            pos.cost_price = (pos.cost_price * pos.shares + px * qty) / new_shares
            pos.shares = new_shares
        return self._fill(order, qty, px, fee, ts, 0.0)

    def _reject(self, order: Order, price: float, ts: datetime, reason: str) -> Fill:
        fill = Fill(
            symbol=order.symbol,
            side=order.side,
            quantity=0,
            price=price,
            fee=0.0,
            timestamp=ts,
            reason=order.reason,
            rejected=True,
            reject_reason=reason,
        )
        logger.info("Reject %s %s %s", order.side.value, order.symbol, reason)
        return fill

    def _fill(self, order: Order, qty: int, px: float, fee: float, ts: datetime, realized: float) -> Fill:
        fill = Fill(
            symbol=order.symbol,
            side=order.side,
            quantity=qty,
            price=px,
            fee=fee,
            timestamp=ts,
            reason=order.reason,
        )
        self.ledger.append_trade(
            {
                "symbol": order.symbol,
                "side": order.side.value,
                "quantity": qty,
                "price": px,
                "fee": fee,
                "realized_pnl": realized,
                "reason": order.reason,
                "timestamp": ts.isoformat(),
                "cash": self.cash,
            }
        )
        logger.info(
            "Fill %s %s %d @ %.4f fee=%.2f cash=%.2f",
            order.side.value,
            order.symbol,
            qty,
            px,
            fee,
            self.cash,
        )
        return fill

    def snapshot(self, marks: dict[str, float]) -> dict[str, Any]:
        equity = self.get_equity(marks)
        return {
            "cash": self.cash,
            "equity": equity,
            "realized_pnl": self.realized_pnl,
            "peak_equity": self.peak_equity,
            "positions": {k: {"shares": v.shares, "available": v.available, "cost": v.cost_price} for k, v in self.positions.items()},
        }
