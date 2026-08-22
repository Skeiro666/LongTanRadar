from __future__ import annotations

import logging
import os
import time
import uuid
from typing import Any, Optional

from ashare.brokers.base import AccountInfo, Broker, OrderResult, PositionInfo
from ashare.models import Order, Side

logger = logging.getLogger("ashare.brokers.xingye_qmt")


class XingyeQmtBroker(Broker):
    """Industrial Securities via local miniQMT (xtquant).

    Requires: miniQMT installed & logged in; env QMT_USERDATA_PATH, QMT_ACCOUNT_ID,
    and I_UNDERSTAND_LIVE=1 when BROKER_MODE=live.
    """

    mode = "live"

    def __init__(
        self,
        userdata_path: str | None = None,
        account_id: str | None = None,
        session_id: int | None = None,
    ) -> None:
        self.userdata_path = userdata_path or os.getenv("QMT_USERDATA_PATH", "")
        self.account_id = account_id or os.getenv("QMT_ACCOUNT_ID", "")
        self.session_id = session_id or int(os.getenv("QMT_SESSION_ID", "123456"))
        self._trader = None
        self._account = None
        self._connected = False

    def connect(self) -> None:
        if os.getenv("I_UNDERSTAND_LIVE", "0") != "1":
            raise RuntimeError("Live blocked: set I_UNDERSTAND_LIVE=1 in .env")
        if not self.userdata_path or not self.account_id:
            raise RuntimeError("Set QMT_USERDATA_PATH and QMT_ACCOUNT_ID in .env")
        try:
            from xtquant.xttrader import XtQuantTrader
            from xtquant.xttype import StockAccount
        except ImportError as exc:
            raise RuntimeError(
                "xtquant not found. Install/login 兴业 miniQMT and add its Python path."
            ) from exc

        trader = XtQuantTrader(self.userdata_path, self.session_id)
        trader.start()
        acc = StockAccount(self.account_id)
        res = trader.connect()
        if res != 0:
            raise RuntimeError(f"QMT connect failed code={res}")
        sub = trader.subscribe(acc)
        if sub != 0:
            logger.warning("QMT subscribe returned %s", sub)
        self._trader = trader
        self._account = acc
        self._connected = True
        logger.info("Connected Xingye/QMT account=%s", self.account_id)

    def get_account(self) -> AccountInfo:
        self._ensure()
        asset = self._trader.query_stock_asset(self._account)
        if asset is None:
            return AccountInfo(0, 0, 0, {})
        cash = float(getattr(asset, "cash", 0) or 0)
        mv = float(getattr(asset, "market_value", 0) or 0)
        total = float(getattr(asset, "total_asset", cash + mv) or (cash + mv))
        return AccountInfo(cash=cash, market_value=mv, equity=total, raw={"asset": str(asset)})

    def get_positions(self) -> list[PositionInfo]:
        self._ensure()
        positions = self._trader.query_stock_positions(self._account) or []
        out: list[PositionInfo] = []
        for p in positions:
            vol = int(getattr(p, "volume", 0) or 0)
            if vol <= 0:
                continue
            out.append(
                PositionInfo(
                    symbol=str(getattr(p, "stock_code", "")),
                    shares=vol,
                    available=int(getattr(p, "can_use_volume", vol) or vol),
                    cost_price=float(getattr(p, "avg_price", 0) or 0),
                )
            )
        return out

    def place_order(self, order: Order, price: float | None = None) -> OrderResult:
        self._ensure()
        from xtquant import xtconstant

        cid = order.client_order_id or str(uuid.uuid4())
        code = order.symbol
        # xtquant often wants 600000.SH style
        if order.side == Side.BUY:
            order_type = xtconstant.STOCK_BUY
        else:
            order_type = xtconstant.STOCK_SELL
        px = float(price or 0)
        # -1 / 0 market depending on version — use latest price limit as safer default
        price_type = xtconstant.FIX_PRICE if px > 0 else xtconstant.LATEST_PRICE
        try:
            oid = self._trader.order_stock(
                self._account,
                code,
                order_type,
                int(order.quantity),
                price_type,
                px,
                "ashare",
                order.reason or cid,
            )
        except Exception as exc:  # noqa: BLE001
            return OrderResult(False, cid, message=str(exc))
        if oid is None or oid < 0:
            return OrderResult(False, cid, message=f"order_stock failed: {oid}")
        return OrderResult(True, cid, broker_order_id=str(oid), message="submitted")

    def cancel_order(self, broker_order_id: str) -> bool:
        self._ensure()
        try:
            self._trader.cancel_order_stock(self._account, int(broker_order_id))
            return True
        except Exception:  # noqa: BLE001
            return False

    def _ensure(self) -> None:
        if not self._connected or self._trader is None:
            self.connect()
