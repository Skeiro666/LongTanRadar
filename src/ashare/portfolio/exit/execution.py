from __future__ import annotations

"""Execution helpers: T close signal → T+1 open fill. Never silent T-close fill."""

from typing import Any

import pandas as pd


def row_is_blocked_sell(row: pd.Series | dict[str, Any]) -> tuple[bool, str]:
    """A-share sell blocks: limit-down / halt / suspension."""
    if bool(row.get("is_halt") or row.get("halt")):
        return True, "halt"
    if bool(row.get("limit_down")):
        return True, "limit_down"
    # pct heuristic if flag missing
    try:
        pct = float(row.get("pct_chg") or 0)
        if pct <= -9.5:
            return True, "limit_down_heuristic"
    except (TypeError, ValueError):
        pass
    return False, ""


def t1_open_fill(
    df: pd.DataFrame,
    signal_idx: int,
) -> dict[str, Any]:
    """
    Signal at bar signal_idx (T close). Execution at T+1 open.
    If T+1 open unavailable → EXECUTION_UNAVAILABLE (do not use T close).
    """
    if signal_idx < 0 or signal_idx >= len(df) - 1:
        return {
            "available": False,
            "status": "EXECUTION_UNAVAILABLE",
            "note": "no_t1_bar",
        }
    nxt = df.iloc[signal_idx + 1]
    if "open" not in df.columns or pd.isna(nxt.get("open")):
        return {
            "available": False,
            "status": "EXECUTION_UNAVAILABLE",
            "note": "t1_open_missing",
        }
    blocked, reason = row_is_blocked_sell(nxt)
    if blocked:
        return {
            "available": False,
            "status": "EXIT_BLOCKED",
            "block_reason": reason,
            "date": str(nxt.get("date")),
            "note": "cannot_sell_at_t1",
        }
    return {
        "available": True,
        "status": "OK",
        "fill_idx": int(signal_idx + 1),
        "fill_date": str(nxt.get("date")),
        "fill_price": float(nxt["open"]),
        "execution": "t1_open",
    }


def round_trip_cost_rate(
    *,
    notional: float = 10_000.0,
    commission_rate: float = 0.00025,
    min_commission: float = 5.0,
    stamp_tax_rate: float = 0.0005,
    transfer_fee_rate: float = 0.00001,
    slippage_bps: float = 5.0,
) -> float:
    """Approximate one-way sell cost rate + half-spread style slippage (research)."""
    commission = max(notional * commission_rate, min_commission) / notional
    stamp = stamp_tax_rate  # sells only
    transfer = transfer_fee_rate
    slip = slippage_bps / 10_000.0
    return float(commission + stamp + transfer + slip)


def apply_net_return(gross: float, cost_rate: float) -> float:
    return float(gross - cost_rate)
