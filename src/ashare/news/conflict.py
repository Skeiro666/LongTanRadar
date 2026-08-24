from __future__ import annotations

from typing import Any

from ashare.news.schema import normalize_direction


def _news_dir(intel: dict[str, Any] | None, events: list[dict[str, Any]] | None = None) -> int:
    d = normalize_direction((intel or {}).get("direction"))
    if d == "positive":
        return 1
    if d == "negative":
        return -1
    if d == "mixed":
        return 0
    for ev in events or []:
        ed = normalize_direction(ev.get("direction") or ev.get("event_direction"))
        if ed == "positive":
            return 1
        if ed == "negative":
            return -1
    return 0


def _quant_dir(candidate: dict[str, Any] | None, price_signal: str | None = None) -> int:
    c = candidate or {}
    try:
        leader = float(c.get("leader_score") or c.get("candidate_score") or 0)
    except (TypeError, ValueError):
        leader = 0.0
    ps = str(price_signal or c.get("price_signal") or "").lower()
    if ps in {"strong", "up", "bull"} or leader >= 0.35:
        return 1
    if ps in {"weak", "down", "bear"} or leader <= 0.12:
        return -1
    return 0


def compute_news_conflict(
    *,
    intelligence: dict[str, Any] | None = None,
    events: list[dict[str, Any]] | None = None,
    candidate: dict[str, Any] | None = None,
    price_signal: str | None = None,
) -> dict[str, Any]:
    """
    0~1: news bullish vs quant weak, or news bearish vs price strong.
    For Adaptive AI Routing — no LLM.
    """
    nd = _news_dir(intelligence, events)
    qd = _quant_dir(candidate, price_signal)
    if nd == 0 or qd == 0:
        score = 0.0
        reason = "insufficient_signals"
    elif nd == qd:
        score = 0.0
        reason = "aligned"
    else:
        score = 0.75 if abs(nd) == 1 else 0.4
        reason = "news_quant_disagreement" if nd > 0 else "news_price_disagreement"
        if nd > 0 and qd < 0:
            reason = "news_positive_quant_weak"
        elif nd < 0 and qd > 0:
            reason = "news_negative_price_strong"
    return {
        "news_conflict": bool(score > 0),
        "conflict_score": round(float(score), 4),
        "news_direction": nd,
        "quant_direction": qd,
        "reason": reason,
    }
