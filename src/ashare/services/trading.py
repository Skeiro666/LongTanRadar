from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

from ashare.brokers.base import AccountInfo, Broker, OrderResult, PositionInfo
from ashare.brokers.paper import PaperBroker
from ashare.brokers.xingye_qmt import XingyeQmtBroker
from ashare.db.pg import database_url_from_env, get_engine
from ashare.db.redis_client import cache_set, redis_url_from_env
from ashare.models import Order, Side
from ashare.services.picks import latest_picks, run_picks
from ashare.symbols import round_lot

logger = logging.getLogger("ashare.services.trading")


class PaperTradingBroker(Broker):
    """PaperBroker adapted to Broker interface; marks from last close optional."""

    mode = "paper"

    def __init__(self, paper: PaperBroker) -> None:
        self.paper = paper
        self._marks: dict[str, float] = {}

    def connect(self) -> None:
        return None

    def set_marks(self, marks: dict[str, float]) -> None:
        self._marks = marks

    def get_account(self) -> AccountInfo:
        eq = self.paper.get_equity(self._marks)
        mv = self.paper.market_value(self._marks)
        return AccountInfo(cash=self.paper.cash, market_value=mv, equity=eq)

    def get_positions(self) -> list[PositionInfo]:
        out = []
        for sym, pos in self.paper.positions.items():
            out.append(
                PositionInfo(
                    symbol=sym,
                    shares=pos.shares,
                    available=pos.available,
                    cost_price=pos.cost_price,
                )
            )
        return out

    def place_order(self, order: Order, price: float | None = None) -> OrderResult:
        from ashare.models import Bar
        from datetime import date

        px = float(price or self._marks.get(order.symbol, 0) or 0)
        if px <= 0:
            return OrderResult(False, order.client_order_id or "", message="no price")
        bar = Bar(
            symbol=order.symbol,
            date=date.today(),
            open=px,
            high=px,
            low=px,
            close=px,
            volume=1e9,
        )
        fill = self.paper.execute(order, bar, px)
        cid = order.client_order_id or str(uuid.uuid4())
        if fill.rejected:
            return OrderResult(False, cid, message=fill.reject_reason)
        self.paper._persist(self._marks)
        return OrderResult(
            True,
            cid,
            broker_order_id=cid,
            message="paper_filled",
            filled_qty=fill.quantity,
            filled_price=fill.price,
        )


def broker_mode(cfg: dict[str, Any]) -> str:
    return (
        os.getenv("BROKER_MODE")
        or str(cfg.get("broker", {}).get("mode", "paper"))
    ).lower()


def build_live_or_paper(cfg: dict[str, Any]) -> Broker:
    mode = broker_mode(cfg)
    if mode == "live":
        b = XingyeQmtBroker(
            userdata_path=os.getenv("QMT_USERDATA_PATH") or cfg.get("broker", {}).get("qmt_userdata_path"),
            account_id=os.getenv("QMT_ACCOUNT_ID") or cfg.get("broker", {}).get("qmt_account_id"),
        )
        b.connect()
        return b
    from ashare.backtest.engine import broker_from_cfg

    paper = broker_from_cfg(
        cfg,
        persist=True,
        reset=bool(cfg.get("paper", {}).get("reset_on_start", False)),
    )
    return PaperTradingBroker(paper)


def _save_order(
    cfg: dict[str, Any],
    *,
    mode: str,
    symbol: str,
    side: str,
    qty: int,
    price: float | None,
    status: str,
    client_order_id: str,
    broker_order_id: str = "",
    reason: str = "",
    error: str = "",
) -> int | None:
    db_url = database_url_from_env(cfg)
    try:
        eng = get_engine(db_url)
        with eng.begin() as conn:
            row = conn.execute(
                text(
                    """
                    INSERT INTO orders
                    (client_order_id, broker_mode, symbol, side, quantity, price, status, broker_order_id, reason, error)
                    VALUES (:cid, :mode, :symbol, :side, :qty, :price, :status, :boid, :reason, :error)
                    RETURNING id
                    """
                ),
                {
                    "cid": client_order_id,
                    "mode": mode,
                    "symbol": symbol,
                    "side": side,
                    "qty": qty,
                    "price": price,
                    "status": status,
                    "boid": broker_order_id,
                    "reason": reason,
                    "error": error,
                },
            ).scalar()
            return int(row) if row else None
    except Exception as exc:  # noqa: BLE001
        logger.warning("save order failed: %s", exc)
        return None


def _save_fill(cfg: dict[str, Any], order_id: int | None, result: OrderResult, symbol: str, side: str, mode: str) -> None:
    if not order_id or not result.ok or result.filled_qty <= 0:
        return
    db_url = database_url_from_env(cfg)
    try:
        eng = get_engine(db_url)
        with eng.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO fills (order_id, symbol, side, quantity, price, fee, broker_mode)
                    VALUES (:oid, :symbol, :side, :qty, :price, 0, :mode)
                    """
                ),
                {
                    "oid": order_id,
                    "symbol": symbol,
                    "side": side,
                    "qty": result.filled_qty,
                    "price": result.filled_price,
                    "mode": mode,
                },
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("save fill failed: %s", exc)


def snapshot_account(cfg: dict[str, Any], broker: Broker) -> dict[str, Any]:
    from ashare.data.names import attach_names

    acc = broker.get_account()
    positions = [
        {
            "symbol": p.symbol,
            "shares": p.shares,
            "available": p.available,
            "cost_price": p.cost_price,
        }
        for p in broker.get_positions()
    ]
    positions = attach_names(positions, cfg)
    payload = {
        "broker_mode": broker.mode,
        "cash": acc.cash,
        "market_value": acc.market_value,
        "equity": acc.equity,
        "positions": positions,
        "as_of": datetime.now(timezone.utc).isoformat(),
    }
    try:
        from ashare.services.pnl import record_equity

        record_equity(cfg, equity=float(acc.equity), cash=float(acc.cash), source="account")
    except Exception:  # noqa: BLE001
        pass
    try:
        cache_set(redis_url_from_env(cfg), f"ashare:account:{broker.mode}", payload, ttl=120)
    except Exception:  # noqa: BLE001
        pass
    db_url = database_url_from_env(cfg)
    try:
        eng = get_engine(db_url)
        import json

        with eng.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO account_snapshot (broker_mode, cash, equity, raw_json)
                    VALUES (:mode, :cash, :equity, CAST(:raw AS jsonb))
                    """
                ),
                {
                    "mode": broker.mode,
                    "cash": acc.cash,
                    "equity": acc.equity,
                    "raw": json.dumps(payload, ensure_ascii=False),
                },
            )
            conn.execute(text("DELETE FROM positions_snapshot WHERE broker_mode = :m"), {"m": broker.mode})
            for p in positions:
                conn.execute(
                    text(
                        """
                        INSERT INTO positions_snapshot
                        (broker_mode, symbol, shares, available, cost_price, market_value)
                        VALUES (:mode, :symbol, :shares, :available, :cost, NULL)
                        """
                    ),
                    {
                        "mode": broker.mode,
                        "symbol": p["symbol"],
                        "shares": p["shares"],
                        "available": p["available"],
                        "cost": p["cost_price"],
                    },
                )
    except Exception as exc:  # noqa: BLE001
        logger.warning("account snapshot pg failed: %s", exc)
        payload["persist_warning"] = str(exc)
    return payload


def place_manual_order(
    cfg: dict[str, Any],
    *,
    symbol: str,
    side: str,
    quantity: int,
    price: float | None = None,
) -> dict[str, Any]:
    from ashare.data.provider import latest_marks
    from ashare.symbols import to_symbol

    broker = build_live_or_paper(cfg)
    broker.connect()
    sym = to_symbol(symbol)
    marks = latest_marks(cfg, [sym])
    if isinstance(broker, PaperTradingBroker):
        broker.set_marks(marks)
    px = float(price) if price is not None else marks.get(sym)
    qty = round_lot(int(quantity), int(cfg.get("trading", {}).get("lot_size", 100)))
    if qty < 100:
        raise ValueError("quantity must be >= 100 (1 lot)")
    cid = str(uuid.uuid4())
    order = Order(
        symbol=sym,
        side=Side(side.upper()),
        quantity=qty,
        reason="manual",
        client_order_id=cid,
    )
    result = broker.place_order(order, price=px)
    oid = _save_order(
        cfg,
        mode=broker.mode,
        symbol=sym,
        side=side.upper(),
        qty=qty,
        price=px,
        status="filled" if result.ok and result.filled_qty else ("submitted" if result.ok else "rejected"),
        client_order_id=result.client_order_id or cid,
        broker_order_id=result.broker_order_id,
        reason="manual",
        error="" if result.ok else result.message,
    )
    _save_fill(cfg, oid, result, sym, side.upper(), broker.mode)
    return {"result": result.__dict__, "account": snapshot_account(cfg, broker)}


def execute_picks(
    cfg: dict[str, Any],
    *,
    regenerate: bool = False,
    force_live: bool = False,
    skip_ai_review: bool = False,
) -> dict[str, Any]:
    """Buy equal-weight picks with available cash; skip names that can't afford 1 lot.

    By default, AI reviews K-line + news and must approve before any buy.
    """
    mode = broker_mode(cfg)
    if mode == "live" and (not force_live or os.getenv("I_UNDERSTAND_LIVE", "0") != "1"):
        raise RuntimeError("Live trading blocked. Set BROKER_MODE=live, I_UNDERSTAND_LIVE=1, and confirm in UI.")

    picks_payload = run_picks(cfg) if regenerate else (latest_picks(cfg) or run_picks(cfg))
    from ashare.research.canonical_decision import extract_trading_decisions

    canonical_approved = extract_trading_decisions(picks_payload)
    all_display_picks = list(picks_payload.get("picks") or [])
    if not all_display_picks and picks_payload.get("canonical_decisions") is None:
        raise RuntimeError("No picks available")

    ai_review: dict[str, Any] | None = None
    decision_chain = picks_payload.get("decision_chain") or {}
    canonical_source = decision_chain.get("canonical_source") or "platform_council"
    if picks_payload.get("canonical_decisions") is not None or any(
        p.get("committee_verdict") for p in all_display_picks
    ):
        approved = (
            canonical_approved
            if picks_payload.get("canonical_decisions") is not None
            else [
                p
                for p in all_display_picks
                if p.get("committee_approve") or str(p.get("committee_verdict") or "").lower() == "buy"
            ]
        )
        rejected = [p for p in all_display_picks if p not in approved]
        ai_review = {
            "summary": f"Canonical Decision ({canonical_source})",
            "source": canonical_source,
            "reviews": all_display_picks,
            "rejected": rejected,
            "approved": approved,
        }
        picks = approved
        picks_payload = {
            **picks_payload,
            "picks": picks,
            "ai_review": {
                "summary": ai_review.get("summary"),
                "source": ai_review.get("source"),
                "reviews": [
                    {
                        "symbol": r.get("symbol"),
                        "name": r.get("name"),
                        "ai_approve": r.get("committee_approve") or r.get("ai_approve"),
                        "ai_confidence": r.get("ai_confidence"),
                        "ai_rationale": r.get("ai_rationale") or r.get("committee_thesis"),
                        "committee_verdict": r.get("committee_verdict"),
                    }
                    for r in (ai_review.get("reviews") or [])
                ],
                "rejected": [
                    {
                        "symbol": r.get("symbol"),
                        "name": r.get("name"),
                        "ai_rationale": r.get("ai_rationale") or r.get("committee_verdict"),
                    }
                    for r in rejected
                ],
            },
        }
        if not picks:
            broker = build_live_or_paper(cfg)
            broker.connect()
            from ashare.data.provider import latest_marks

            held = [p.symbol for p in broker.get_positions()]
            if held and isinstance(broker, PaperTradingBroker):
                try:
                    broker.set_marks(latest_marks(cfg, held))
                except Exception:  # noqa: BLE001
                    pass
            return {
                "picks": picks_payload,
                "orders": [],
                "account": snapshot_account(cfg, broker),
                "skipped_buy": True,
                "ai_rejected_all": True,
                "ai_review": picks_payload.get("ai_review"),
                "message": ai_review.get("summary") or "Canonical Decision 未给出 buy，本轮不买入",
            }
    elif not skip_ai_review and bool((cfg.get("ai") or {}).get("trade_review", True)):
        from ashare.ai.trade_review import review_trade_candidates
        from pathlib import Path
        import json

        ai_review = review_trade_candidates(cfg, picks)
        picks = list(ai_review.get("approved") or [])
        picks_payload = {
            **picks_payload,
            "picks": picks,
            "ai_review": {
                "summary": ai_review.get("summary"),
                "source": ai_review.get("source"),
                "reviews": [
                    {
                        "symbol": r.get("symbol"),
                        "name": r.get("name"),
                        "ai_approve": r.get("ai_approve"),
                        "ai_confidence": r.get("ai_confidence"),
                        "ai_rationale": r.get("ai_rationale"),
                    }
                    for r in (ai_review.get("reviews") or [])
                ],
                "rejected": [
                    {"symbol": r.get("symbol"), "name": r.get("name"), "ai_rationale": r.get("ai_rationale")}
                    for r in (ai_review.get("rejected") or [])
                ],
            },
        }
        try:
            out = Path(cfg["_root"]) / "data" / "trade_review_latest.json"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(ai_review, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            logger.warning("persist trade review failed: %s", exc)
        if not picks:
            broker = build_live_or_paper(cfg)
            broker.connect()
            from ashare.data.provider import latest_marks

            held = [p.symbol for p in broker.get_positions()]
            if held and isinstance(broker, PaperTradingBroker):
                try:
                    broker.set_marks(latest_marks(cfg, held))
                except Exception:  # noqa: BLE001
                    pass
            return {
                "picks": picks_payload,
                "orders": [],
                "account": snapshot_account(cfg, broker),
                "skipped_buy": True,
                "ai_rejected_all": True,
                "ai_review": picks_payload.get("ai_review"),
                "message": ai_review.get("summary") or "AI 审查全部拒绝，本轮不买入",
            }
    else:
        picks = all_display_picks

    broker = build_live_or_paper(cfg)
    broker.connect()

    from ashare.data.provider import latest_marks

    held = [p.symbol for p in broker.get_positions()]
    need = list(dict.fromkeys([p["symbol"] for p in picks] + held))
    marks = latest_marks(cfg, need)
    if isinstance(broker, PaperTradingBroker):
        broker.set_marks(marks)

    acc = broker.get_account()
    lot = int(cfg.get("trading", {}).get("lot_size", 100))
    # Prefer affordable names for small accounts
    affordable = []
    for p in picks:
        px = marks.get(p["symbol"], 0.0)
        if px > 0 and px * lot <= acc.cash * 0.98:
            affordable.append(p)
    if not affordable:
        # Already fully invested / cash leftover too small — evaluate only, don't crash agent.
        from ashare.data.names import attach_names

        picks_payload = {**picks_payload, "note": f"cash {acc.cash:.2f} too small for 1 lot; hold only"}
        picks_payload["picks"] = attach_names(list(picks_payload.get("picks") or []), cfg)
        out = {
            "picks": picks_payload,
            "orders": [],
            "account": snapshot_account(cfg, broker),
            "skipped_buy": True,
            "message": f"Cash {acc.cash:.2f} too small to buy 1 lot — keeping current positions",
        }
        if ai_review is not None:
            out["ai_review"] = picks_payload.get("ai_review")
        return out

    # Renormalize weights among affordable
    n = len(affordable)
    for p in affordable:
        p["weight"] = 1.0 / n

    results = []
    for p in affordable:
        sym = p["symbol"]
        w = float(p.get("weight") or 0)
        px = marks.get(sym, 0.0)
        if px <= 0:
            results.append({"symbol": sym, "ok": False, "message": "no price"})
            continue
        budget = min(acc.cash, acc.equity * w)
        qty = round_lot(int(budget / px), lot)
        if qty < lot:
            results.append({"symbol": sym, "ok": False, "message": "budget too small for 1 lot"})
            continue
        cid = str(uuid.uuid4())
        order = Order(symbol=sym, side=Side.BUY, quantity=qty, reason="picks+ai_ok", client_order_id=cid)
        res = broker.place_order(order, price=px)
        oid = _save_order(
            cfg,
            mode=broker.mode,
            symbol=sym,
            side="BUY",
            qty=qty,
            price=px,
            status="filled" if res.ok and res.filled_qty else ("submitted" if res.ok else "rejected"),
            client_order_id=res.client_order_id or cid,
            broker_order_id=res.broker_order_id,
            reason="picks+ai_ok",
            error="" if res.ok else res.message,
        )
        _save_fill(cfg, oid, res, sym, "BUY", broker.mode)
        results.append({"symbol": sym, "quantity": qty, **res.__dict__})
        acc = broker.get_account()

    picks_payload = {**picks_payload, "picks": affordable, "note": "filtered to affordable lots"}
    from ashare.data.names import attach_names

    picks_payload["picks"] = attach_names(picks_payload["picks"], cfg)
    for o in results:
        if "symbol" in o:
            named = attach_names([{"symbol": o["symbol"]}], cfg)[0]
            o["name"] = named.get("name", "")
    return {
        "picks": picks_payload,
        "orders": results,
        "account": snapshot_account(cfg, broker),
        "ai_review": picks_payload.get("ai_review"),
    }


def reset_paper_account(cfg: dict[str, Any]) -> dict[str, Any]:
    """Wipe paper state + pnl curve and restore initial balance."""
    import copy
    from pathlib import Path

    from ashare.backtest.engine import broker_from_cfg
    from ashare.services.pnl import record_equity, pnl_summary

    cfg = copy.deepcopy(cfg)
    cfg.setdefault("broker", {})["mode"] = "paper"
    os.environ["BROKER_MODE"] = "paper"
    paper = cfg.setdefault("paper", {})
    state = Path(paper.get("state_file", "data/paper_state.json"))
    if state.exists():
        state.unlink()
    pnl_path = Path(cfg["_root"]) / "data" / "pnl_curve.json"
    if pnl_path.exists():
        pnl_path.unlink()
    agent_path = Path(cfg["_root"]) / "data" / "agent_state.json"
    if agent_path.exists():
        agent_path.unlink()
    overrides = Path(cfg["_root"]) / "config" / "agent_overrides.yaml"
    if overrides.exists():
        overrides.unlink()

    broker = broker_from_cfg(cfg, persist=True, reset=True)
    cash = float(broker.cash)
    record_equity(cfg, equity=cash, cash=cash, source="reset")
    return {
        "ok": True,
        "cash": cash,
        "equity": cash,
        "positions": [],
        "pnl": pnl_summary(cfg),
        "message": f"已清空，本金恢复为 {cash:.0f}",
    }


def run_auto_paper(cfg: dict[str, Any], *, reset: bool = True) -> dict[str, Any]:
    """Reset paper account (optional), pick stocks, auto-buy. Always paper mode."""
    import copy
    from pathlib import Path

    cfg = copy.deepcopy(cfg)
    cfg.setdefault("broker", {})["mode"] = "paper"
    os.environ["BROKER_MODE"] = "paper"
    paper = cfg.setdefault("paper", {})
    if reset:
        reset_paper_account(cfg)
        paper["reset_on_start"] = True
    from ashare.data.provider import ensure_panel

    ensure_panel(cfg)
    picks = run_picks(cfg)
    traded = execute_picks(cfg, regenerate=False, force_live=False)
    return {"step": "auto_paper", "initial_balance": paper.get("initial_balance"), **traded, "picks_raw": picks}


def list_orders(cfg: dict[str, Any], limit: int = 50) -> list[dict[str, Any]]:
    from ashare.data.names import attach_names

    db_url = database_url_from_env(cfg)
    try:
        eng = get_engine(db_url)
        with eng.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT id, client_order_id, broker_mode, symbol, side, quantity, price, status, "
                    "broker_order_id, reason, error, created_at FROM orders ORDER BY id DESC LIMIT :n"
                ),
                {"n": limit},
            ).mappings().all()
            return attach_names([dict(r) for r in rows], cfg)
    except Exception as exc:  # noqa: BLE001
        logger.warning("list orders failed: %s", exc)
        return []
