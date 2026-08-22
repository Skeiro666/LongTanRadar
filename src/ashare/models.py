from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, Optional


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    MARKET = "MARKET"


@dataclass
class Bar:
    symbol: str
    date: date
    open: float
    high: float
    low: float
    close: float
    volume: float
    amount: float = 0.0
    pct_chg: float = 0.0
    is_st: bool = False
    is_halt: bool = False
    limit_up: bool = False
    limit_down: bool = False


@dataclass
class OrderIntent:
    symbol: str
    side: Side
    quantity: int
    reason: str = ""
    reduce_only: bool = False


@dataclass
class Order:
    symbol: str
    side: Side
    quantity: int
    order_type: OrderType = OrderType.MARKET
    reason: str = ""
    reduce_only: bool = False
    client_order_id: str | None = None


@dataclass
class Fill:
    symbol: str
    side: Side
    quantity: int
    price: float
    fee: float
    timestamp: datetime
    reason: str = ""
    rejected: bool = False
    reject_reason: str = ""


@dataclass
class Position:
    symbol: str
    shares: int = 0
    available: int = 0
    cost_price: float = 0.0

    @property
    def market_value(self) -> float:
        return 0.0


@dataclass
class AccountSnapshot:
    cash: float
    equity: float
    realized_pnl: float
    peak_equity: float
    daily_start_equity: float
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["timestamp"] = self.timestamp.isoformat()
        return d
