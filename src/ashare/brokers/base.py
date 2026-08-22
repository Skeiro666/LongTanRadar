from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional

from ashare.models import Order, Side


@dataclass
class AccountInfo:
    cash: float
    market_value: float
    equity: float
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class PositionInfo:
    symbol: str
    shares: int
    available: int
    cost_price: float


@dataclass
class OrderResult:
    ok: bool
    client_order_id: str
    broker_order_id: str = ""
    message: str = ""
    filled_qty: int = 0
    filled_price: float = 0.0


class Broker(ABC):
    mode: str = "paper"

    @abstractmethod
    def connect(self) -> None: ...

    @abstractmethod
    def get_account(self) -> AccountInfo: ...

    @abstractmethod
    def get_positions(self) -> list[PositionInfo]: ...

    @abstractmethod
    def place_order(self, order: Order, price: float | None = None) -> OrderResult: ...

    def cancel_order(self, broker_order_id: str) -> bool:
        return False
