from __future__ import annotations

from typing import Any

import pandas as pd

# V5.2 event lifecycle — research semantics only, never trading actions.
LIFECYCLE_NEW = "NEW"
LIFECYCLE_PRICED_IN = "PRICED_IN"
LIFECYCLE_RESOLVED = "RESOLVED"
LIFECYCLE_REJECTED = "REJECTED"

_RISK_SCORE = {"HIGH": 0.85, "MEDIUM": 0.50, "LOW": 0.15, "UNKNOWN": 0.0}


def price_in_score(
    *,
    price_in_risk: str = "UNKNOWN",
    price_reaction: dict[str, Any] | None = None,
) -> float:
    """
    0–1 score: higher = more likely information is already in the price.
    Display / feature only — not mixed into BUY score.
    """
    risk = (price_in_risk or "UNKNOWN").upper()
    base = float(_RISK_SCORE.get(risk, 0.0))
    rx = price_reaction or {}
    if rx.get("available"):
        prs = abs(float(rx.get("price_reaction_score") or 0))
        base = max(base, min(1.0, prs))
    return round(base, 4)


def _parse_day(raw: Any) -> pd.Timestamp | None:
    if raw is None or raw == "":
        return None
    ts = pd.to_datetime(str(raw)[:19], errors="coerce")
    if pd.isna(ts):
        ts = pd.to_datetime(str(raw)[:10], errors="coerce")
    if pd.isna(ts):
        return None
    return pd.Timestamp(ts).normalize()


def _trading_days_since(event_day: pd.Timestamp, as_of_day: pd.Timestamp) -> int | None:
    if event_day is None or as_of_day is None:
        return None
    if as_of_day <= event_day:
        return 0
    try:
        days = pd.bdate_range(event_day + pd.Timedelta(days=1), as_of_day)
        return len(days)
    except Exception:  # noqa: BLE001
        return int((as_of_day - event_day).days)


def _outcome_fully_resolved(outcome: dict[str, Any] | None, *, min_horizon: int = 20) -> bool:
    if not outcome or outcome.get("outcome_status") != "ok":
        return False
    cells = outcome.get("horizons") or {}
    cell = cells.get(str(min_horizon)) or cells.get(min_horizon)
    if not isinstance(cell, dict):
        return False
    return cell.get("actual_return") is not None and cell.get("status") != "pending"


def compute_event_lifecycle(
    nc: dict[str, Any],
    *,
    as_of: str | None = None,
    outcome: dict[str, Any] | None = None,
    resolve_after_trading_days: int = 20,
) -> dict[str, Any]:
    """
    NEW → PRICED_IN → RESOLVED (or REJECTED).
    Does not change trading decisions.
    """
    status = str(nc.get("status") or "DISCOVERED").upper()
    if status == "REJECTED":
        return {
            "lifecycle_status": LIFECYCLE_REJECTED,
            "lifecycle_reason": str(nc.get("reject_reason") or "rejected"),
        }

    rx = dict(nc.get("price_reaction") or {})
    risk = str(nc.get("price_in_risk") or rx.get("price_in_risk") or "UNKNOWN").upper()
    score = price_in_score(price_in_risk=risk, price_reaction=rx)

    if _outcome_fully_resolved(outcome, min_horizon=resolve_after_trading_days):
        return {
            "lifecycle_status": LIFECYCLE_RESOLVED,
            "lifecycle_reason": f"outcome_T+{resolve_after_trading_days}",
            "price_in_score": score,
        }

    as_of_day = _parse_day(as_of)
    event_day = _parse_day(rx.get("event_day") or nc.get("event_time") or nc.get("published_at"))
    age = _trading_days_since(event_day, as_of_day) if event_day and as_of_day else None
    if age is not None and age >= resolve_after_trading_days:
        return {
            "lifecycle_status": LIFECYCLE_RESOLVED,
            "lifecycle_reason": f"elapsed_{age}td",
            "price_in_score": score,
        }

    if risk in {"HIGH", "MEDIUM"} or score >= 0.45:
        return {
            "lifecycle_status": LIFECYCLE_PRICED_IN,
            "lifecycle_reason": f"price_in_risk={risk}" if risk in {"HIGH", "MEDIUM"} else "price_reaction_elevated",
            "price_in_score": score,
        }

    return {
        "lifecycle_status": LIFECYCLE_NEW,
        "lifecycle_reason": "fresh_discovery",
        "price_in_score": score,
    }


def apply_event_lifecycle(
    nc: dict[str, Any],
    *,
    as_of: str | None = None,
    outcome: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Merge lifecycle fields onto a NewsCandidate dict."""
    out = dict(nc)
    lc = compute_event_lifecycle(out, as_of=as_of, outcome=outcome)
    out["lifecycle_status"] = lc["lifecycle_status"]
    out["lifecycle_reason"] = lc.get("lifecycle_reason") or ""
    out["price_in_score"] = lc.get("price_in_score") or price_in_score(
        price_in_risk=str(out.get("price_in_risk") or "UNKNOWN"),
        price_reaction=out.get("price_reaction"),
    )
    # Keep legacy status for funnel reject; lifecycle is orthogonal.
    if out.get("lifecycle_status") == LIFECYCLE_REJECTED and out.get("status") != "REJECTED":
        out["status"] = "REJECTED"
    elif out.get("status") in {"", "DISCOVERED"} and out.get("lifecycle_status") == LIFECYCLE_NEW:
        out["status"] = "DISCOVERED"
    return out
