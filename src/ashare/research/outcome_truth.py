from __future__ import annotations

from typing import Any

PRIMARY_PAPER_FILL = "paper_fill"
PRIMARY_SIGNAL_CLOSE = "signal_close"


def resolve_primary_horizons(outcome: dict[str, Any]) -> tuple[dict[str, Any], str]:
    """
    Single truth priority: paper fill entry > signal-day close entry.
    """
    execution = outcome.get("execution") or {}
    fill_hz = execution.get("horizons_from_fill")
    if execution.get("available") and isinstance(fill_hz, dict) and fill_hz:
        return fill_hz, PRIMARY_PAPER_FILL
    return dict(outcome.get("horizons") or {}), PRIMARY_SIGNAL_CLOSE


def apply_primary_truth(outcomes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for outcome in outcomes:
        horizons, source = resolve_primary_horizons(outcome)
        outcome["primary_source"] = source
        outcome["primary_horizons"] = horizons
    return outcomes


def summarize_portfolio_attribution(
    outcomes: list[dict[str, Any]],
    *,
    horizon: str = "5",
) -> dict[str, Any]:
    """Aggregate primary-horizon metrics for dashboard / pnl cross-link."""
    rets: list[float] = []
    mkt: list[float] = []
    sel: list[float] = []
    n_fill = 0
    n_signal = 0
    for o in outcomes:
        source = str(o.get("primary_source") or PRIMARY_SIGNAL_CLOSE)
        if source == PRIMARY_PAPER_FILL:
            n_fill += 1
        else:
            n_signal += 1
        cell = (o.get("primary_horizons") or {}).get(str(horizon)) or {}
        if cell.get("status") == "pending":
            continue
        if cell.get("actual_return") is not None:
            rets.append(float(cell["actual_return"]))
        if cell.get("market_alpha") is not None:
            mkt.append(float(cell["market_alpha"]))
        if cell.get("selection_alpha") is not None:
            sel.append(float(cell["selection_alpha"]))
    if not rets:
        return {
            "available": False,
            "horizon": str(horizon),
            "insufficient_sample": True,
            "note": "no_primary_horizon_returns",
        }

    def _mean(xs: list[float]) -> float | None:
        return float(sum(xs) / len(xs)) if xs else None

    return {
        "available": True,
        "horizon": str(horizon),
        "n": len(rets),
        "n_paper_fill": n_fill,
        "n_signal_close": n_signal,
        "primary_source_rule": f"{PRIMARY_PAPER_FILL} > {PRIMARY_SIGNAL_CLOSE}",
        "mean_total_return": _mean(rets),
        "mean_market_alpha": _mean(mkt),
        "mean_selection_alpha": _mean(sel),
        "insufficient_sample": len(rets) < 2,
    }
