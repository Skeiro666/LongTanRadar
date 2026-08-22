from __future__ import annotations

import logging
from typing import Any

import pandas as pd
from sqlalchemy import text

from ashare.config_loaders import load_yaml_config
from ashare.db.pg import database_url_from_env, get_engine
from ashare.symbols import to_symbol

logger = logging.getLogger("ashare.research.execution_tracking")


def _tracking_cfg(cfg: dict[str, Any]) -> dict[str, Any]:
    return dict(load_yaml_config(cfg, "research").get("tracking") or {})


def load_paper_fills(cfg: dict[str, Any], *, symbols: list[str] | None = None) -> dict[str, list[dict[str, Any]]]:
    """Load paper fills from Postgres grouped by symbol (most recent first per symbol)."""
    if not _tracking_cfg(cfg).get("execution_tracking", True):
        return {}
    db_url = database_url_from_env(cfg)
    try:
        eng = get_engine(db_url)
    except Exception as exc:  # noqa: BLE001
        logger.debug("execution fills DB unavailable: %s", exc)
        return {}
    sym_filter = ""
    params: dict[str, Any] = {}
    if symbols:
        syms = [to_symbol(s) for s in symbols]
        sym_filter = "AND f.symbol = ANY(:syms)"
        params["syms"] = syms
    sql = f"""
        SELECT f.symbol, f.side, f.quantity, f.price, f.traded_at, f.broker_mode, o.reason
        FROM fills f
        LEFT JOIN orders o ON o.id = f.order_id
        WHERE f.broker_mode = 'paper' {sym_filter}
        ORDER BY f.traded_at DESC
    """
    try:
        with eng.connect() as conn:
            rows = conn.execute(text(sql), params).mappings().all()
    except Exception as exc:  # noqa: BLE001
        logger.debug("execution fills query failed: %s", exc)
        return {}

    by_sym: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        sym = to_symbol(str(row["symbol"]))
        by_sym.setdefault(sym, []).append(
            {
                "symbol": sym,
                "side": str(row["side"] or "").upper(),
                "quantity": int(row["quantity"] or 0),
                "price": float(row["price"] or 0),
                "traded_at": row["traded_at"].isoformat() if row["traded_at"] else None,
                "reason": row.get("reason") or "",
            }
        )
    return by_sym


def attach_paper_execution(
    outcome: dict[str, Any],
    report: dict[str, Any],
    fills_by_sym: dict[str, list[dict[str, Any]]],
    panel: dict[str, pd.DataFrame] | None = None,
) -> dict[str, Any]:
    """
    Link first paper BUY fill after research_time to outcome.
    Adds execution block + optional fill-based horizon returns (T+1 fill entry).
    """
    sym = to_symbol(str(outcome.get("symbol") or report.get("symbol") or ""))
    research_time = report.get("research_time") or report.get("as_of")
    if not research_time:
        outcome["execution"] = {"available": False, "note": "no_research_time"}
        return outcome

    rt = pd.Timestamp(str(research_time)[:19])
    fills = fills_by_sym.get(sym) or []
    buy_fills = []
    for f in fills:
        if str(f.get("side") or "").upper() != "BUY":
            continue
        ts = f.get("traded_at")
        if not ts:
            continue
        if pd.Timestamp(ts) >= rt:
            buy_fills.append(f)
    if not buy_fills:
        outcome["execution"] = {"available": False, "note": "no_paper_fill_after_signal"}
        return outcome

    fill = sorted(buy_fills, key=lambda x: x.get("traded_at") or "")[0]
    fill_px = float(fill.get("price") or 0)
    if fill_px <= 0:
        outcome["execution"] = {"available": False, "note": "invalid_fill_price"}
        return outcome

    signal_close = None
    df = (panel or {}).get(sym)
    if df is not None and not df.empty:
        d = df.copy()
        d["date"] = pd.to_datetime(d["date"])
        hist = d[d["date"] <= rt.normalize()]
        if not hist.empty:
            signal_close = float(hist.iloc[-1]["close"])

    slippage = None
    if signal_close and signal_close > 0:
        slippage = fill_px / signal_close - 1.0

    outcome["execution"] = {
        "available": True,
        "entry_source": "paper_fill",
        "decision_id": report.get("research_id"),
        "research_session_id": report.get("research_id"),
        "snapshot_id": report.get("research_id"),
        "symbol": sym,
        "signal_time": str(research_time)[:19] if research_time else None,
        "order_time": fill.get("traded_at"),
        "fill_time": fill.get("traded_at"),
        "fill_price": fill_px,
        "fill_qty": fill.get("quantity"),
        "quantity": fill.get("quantity"),
        "traded_at": fill.get("traded_at"),
        "signal_close": signal_close,
        "slippage_vs_signal_close": slippage,
        "reason": fill.get("reason") or "",
    }

    if df is not None and not df.empty:
        fill_dt = pd.Timestamp(str(fill.get("traded_at"))[:10])
        d = df.copy()
        d["date"] = pd.to_datetime(d["date"])
        fut = d[d["date"] > fill_dt]
        fill_horizons: dict[str, Any] = {}
        for h_str, cell in (outcome.get("horizons") or {}).items():
            if not isinstance(cell, dict) or cell.get("status") == "pending":
                continue
            try:
                h = int(h_str)
            except ValueError:
                continue
            if len(fut) < h:
                fill_horizons[h_str] = {"status": "pending"}
                continue
            exit_px = float(fut.iloc[h - 1]["close"])
            fill_ret = exit_px / fill_px - 1.0
            bench = cell.get("benchmark_return")
            fill_horizons[h_str] = {
                "actual_return": fill_ret,
                "total_return": fill_ret,
                "benchmark_return": bench,
                "market_benchmark_return": cell.get("market_benchmark_return"),
                "universe_benchmark_return": cell.get("universe_benchmark_return"),
                "market_alpha": (fill_ret - float(cell["market_benchmark_return"]))
                if cell.get("market_benchmark_return") is not None
                else None,
                "selection_alpha": (fill_ret - float(cell["universe_benchmark_return"]))
                if cell.get("universe_benchmark_return") is not None
                else None,
                "excess_return": (fill_ret - float(bench)) if bench is not None else None,
                "entry_source": "paper_fill",
            }
        if fill_horizons:
            outcome["execution"]["horizons_from_fill"] = fill_horizons

    return outcome
