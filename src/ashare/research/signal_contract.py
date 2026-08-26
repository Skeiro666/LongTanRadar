"""Candidate / research signal contract: VALID vs ZERO vs MISSING vs UNAVAILABLE.

Never coerce missing/unavailable to 0 for gating or bearish inference.
"""

from __future__ import annotations

from typing import Any

STATUS_VALID = "VALID"
STATUS_ZERO = "ZERO"
STATUS_MISSING = "MISSING"
STATUS_UNAVAILABLE = "UNAVAILABLE"
STATUS_STALE = "STALE"
STATUS_FAILED = "FAILED"

DATA_QUALITY_COMPLETE = "COMPLETE"
DATA_QUALITY_PARTIAL = "PARTIAL"
DATA_QUALITY_DEGRADED = "DEGRADED"
DATA_QUALITY_STALE = "STALE"
DATA_QUALITY_FAILED = "FAILED"


def classify_numeric(raw: Any, *, unavailable: bool = False, failed: bool = False, stale: bool = False) -> dict[str, Any]:
    """Normalize a score-like field into an explicit availability contract."""
    if failed:
        return {"value": None, "status": STATUS_FAILED, "available": False}
    if unavailable:
        return {"value": None, "status": STATUS_UNAVAILABLE, "available": False}
    if stale:
        try:
            v = float(raw)
        except Exception:  # noqa: BLE001
            return {"value": None, "status": STATUS_STALE, "available": False}
        return {"value": v, "status": STATUS_STALE, "available": True}
    if raw is None:
        return {"value": None, "status": STATUS_MISSING, "available": False}
    if isinstance(raw, str) and raw.strip().lower() in {"", "none", "null", "nan", "unavailable", "missing"}:
        return {"value": None, "status": STATUS_UNAVAILABLE if "unavail" in raw.lower() else STATUS_MISSING, "available": False}
    try:
        v = float(raw)
    except Exception:  # noqa: BLE001
        return {"value": None, "status": STATUS_MISSING, "available": False}
    if v != v:  # NaN
        return {"value": None, "status": STATUS_MISSING, "available": False}
    if abs(v) < 1e-15:
        return {"value": 0.0, "status": STATUS_ZERO, "available": True}
    return {"value": float(v), "status": STATUS_VALID, "available": True}


def read_signal(candidate: dict[str, Any], *keys: str, nested: dict[str, Any] | None = None) -> dict[str, Any]:
    """Read first present key; honor explicit *_status / *_available fields when present."""
    for key in keys:
        status_key = f"{key}_status"
        avail_key = f"{key}_available"
        if key in candidate or (nested and key in nested):
            raw = candidate.get(key) if key in candidate else (nested or {}).get(key)
            if candidate.get(status_key) or (nested or {}).get(status_key):
                st = str(candidate.get(status_key) or (nested or {}).get(status_key) or "").upper()
                if st in {STATUS_UNAVAILABLE, STATUS_MISSING, STATUS_FAILED, STATUS_STALE}:
                    return classify_numeric(
                        raw,
                        unavailable=st == STATUS_UNAVAILABLE,
                        failed=st == STATUS_FAILED,
                        stale=st == STATUS_STALE,
                    )
            if avail_key in candidate and candidate.get(avail_key) is False:
                return classify_numeric(raw, unavailable=True)
            if nested and avail_key in nested and nested.get(avail_key) is False:
                return classify_numeric(raw, unavailable=True)
            return classify_numeric(raw)
        # explicit status without value
        if status_key in candidate:
            st = str(candidate.get(status_key) or "").upper()
            return classify_numeric(
                None,
                unavailable=st == STATUS_UNAVAILABLE,
                failed=st == STATUS_FAILED,
                stale=st == STATUS_STALE,
            )
    return classify_numeric(None)


def extract_candidate_signals(candidate: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Canonical signal bundle for gate / council / audit."""
    pi = candidate.get("profit_inflection") if isinstance(candidate.get("profit_inflection"), dict) else {}
    ev = candidate.get("event") if isinstance(candidate.get("event"), dict) else {}
    news = candidate.get("news_package") if isinstance(candidate.get("news_package"), dict) else {}
    quant = candidate.get("quant") if isinstance(candidate.get("quant"), dict) else {}

    ml_status = str(candidate.get("ml_status") or "").lower()
    if ml_status in {"no_model", "unavailable"}:
        ml = classify_numeric(None, unavailable=True)
    elif ml_status in {"failed", "error"}:
        ml = classify_numeric(None, failed=True)
    else:
        ml = read_signal(candidate, "ml_prediction", "ml_rank_score")
        if not ml["available"] and quant:
            ml = read_signal(quant, "ml_prediction", "ml_rank_score")

    if candidate.get("profit_status") in {"UNAVAILABLE", "unavailable", "FAILED", "failed"} or (
        pi and pi.get("available") is False
    ):
        profit = classify_numeric(
            None,
            unavailable=True,
            failed=str(candidate.get("profit_status") or "").lower() == "failed",
        )
    else:
        profit = read_signal(candidate, "profit_score")
        if not profit["available"] and pi:
            profit = read_signal(pi, "score", "profit_score")

    event = read_signal(candidate, "event_score")
    if not event["available"] and ev:
        event = read_signal(ev, "score", "event_score")
    if not event["available"] and candidate.get("event_status") in {"unavailable", "failed"}:
        event = classify_numeric(
            None,
            unavailable=candidate.get("event_status") == "unavailable",
            failed=candidate.get("event_status") == "failed",
        )

    news_sig = read_signal(candidate, "news_score", "news_intelligence_score")
    if not news_sig["available"]:
        if news.get("news_data_incomplete") or news.get("skipped") or candidate.get("news_status") in {
            "unavailable",
            "failed",
        }:
            news_sig = classify_numeric(
                None,
                unavailable=True,
                failed=candidate.get("news_status") == "failed",
            )
        elif news:
            news_sig = read_signal(news, "net_event_score", "news_intelligence_score")

    leader = read_signal(candidate, "leader_score")
    if not leader["available"] and quant:
        leader = read_signal(quant, "leader_score")

    return {
        "candidate_score": read_signal(candidate, "candidate_score", "score"),
        "leader_score": leader,
        "ml_prediction": ml,
        "profit_score": profit,
        "event_score": event,
        "news_score": news_sig,
        "hypothesis_count": classify_numeric(len(candidate.get("research_hypotheses") or [])),
    }


def numeric_or_none(sig: dict[str, Any]) -> float | None:
    if not sig or not sig.get("available"):
        return None
    return float(sig["value"]) if sig.get("value") is not None else None


def meets_threshold(sig: dict[str, Any], threshold: float) -> bool:
    """True only when value is available and >= threshold. Missing never meets."""
    v = numeric_or_none(sig)
    return v is not None and v >= float(threshold)


def soft_value_for_display(sig: dict[str, Any]) -> float | None:
    """For serialization — never invent 0 for missing."""
    return numeric_or_none(sig)


def data_quality_from_signals(signals: dict[str, dict[str, Any]]) -> str:
    keys = ("ml_prediction", "profit_score", "event_score", "news_score", "leader_score")
    states = [str((signals.get(k) or {}).get("status") or STATUS_MISSING) for k in keys]
    if any(s == STATUS_FAILED for s in states):
        return DATA_QUALITY_FAILED
    if any(s == STATUS_STALE for s in states):
        return DATA_QUALITY_STALE
    avail = sum(1 for s in states if s in {STATUS_VALID, STATUS_ZERO})
    if avail == len(keys):
        return DATA_QUALITY_COMPLETE
    if avail == 0:
        return DATA_QUALITY_DEGRADED
    return DATA_QUALITY_PARTIAL


def attach_signal_contract(candidate: dict[str, Any]) -> dict[str, Any]:
    """Annotate candidate in-place with signal contract + data_quality (no score invention)."""
    signals = extract_candidate_signals(candidate)
    candidate["signals"] = signals
    candidate["data_quality"] = data_quality_from_signals(signals)
    # Flatten availability for report consumers without coercing missing→0
    for name, sig in signals.items():
        if name == "hypothesis_count":
            continue
        candidate[f"{name}_status"] = sig.get("status")
        candidate[f"{name}_available"] = bool(sig.get("available"))
        # Keep numeric only when available; do not write 0 for missing
        if sig.get("available") and sig.get("value") is not None:
            if name == "ml_prediction" and candidate.get("ml_prediction") is None:
                candidate["ml_prediction"] = sig["value"]
            if name == "profit_score" and candidate.get("profit_score") is None:
                candidate["profit_score"] = sig["value"]
            if name == "event_score" and candidate.get("event_score") is None:
                candidate["event_score"] = sig["value"]
            if name == "news_score" and candidate.get("news_score") is None:
                candidate["news_score"] = sig["value"]
    return candidate


def serialize_signal_fields(candidate: dict[str, Any]) -> dict[str, Any]:
    """Fields safe to persist on dated reports for audit SSOT."""
    signals = candidate.get("signals") or extract_candidate_signals(candidate)
    out: dict[str, Any] = {
        "data_quality": candidate.get("data_quality") or data_quality_from_signals(signals),
        "ml_status": candidate.get("ml_status"),
    }
    for name in ("candidate_score", "leader_score", "ml_prediction", "profit_score", "event_score", "news_score"):
        sig = signals.get(name) or {}
        out[name] = soft_value_for_display(sig)
        out[f"{name}_status"] = sig.get("status")
        out[f"{name}_available"] = bool(sig.get("available"))
    return out
