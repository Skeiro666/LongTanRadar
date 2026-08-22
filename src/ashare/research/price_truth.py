"""V5.4 Price truth — explicit entry prices; modules must not mix."""

from __future__ import annotations

from typing import Any

ENTRY_SIGNAL = "signal_price"
ENTRY_NOTIFY = "notify_price"
ENTRY_PAPER_FILL = "paper_fill_price"


def signal_price_from_outcome(outcome: dict[str, Any]) -> float | None:
    if outcome.get("signal_price") is not None:
        try:
            return float(outcome["signal_price"])
        except (TypeError, ValueError):
            pass
    exec_block = outcome.get("execution") or {}
    if exec_block.get("signal_close") is not None:
        try:
            return float(exec_block["signal_close"])
        except (TypeError, ValueError):
            pass
    return None


def paper_fill_price_from_outcome(outcome: dict[str, Any]) -> float | None:
    if outcome.get("paper_fill_price") is not None:
        try:
            return float(outcome["paper_fill_price"])
        except (TypeError, ValueError):
            pass
    exec_block = outcome.get("execution") or {}
    if exec_block.get("fill_price") is not None:
        try:
            return float(exec_block["fill_price"])
        except (TypeError, ValueError):
            pass
    return None


def attach_signal_price(outcome: dict[str, Any], price: float | None) -> dict[str, Any]:
    if price is not None and price > 0:
        outcome["signal_price"] = float(price)
        outcome["entry_type_research"] = ENTRY_SIGNAL
    return outcome


def attach_paper_fill_price(outcome: dict[str, Any], price: float | None) -> dict[str, Any]:
    if price is not None and price > 0:
        outcome["paper_fill_price"] = float(price)
        outcome["entry_type_paper"] = ENTRY_PAPER_FILL
    return outcome
