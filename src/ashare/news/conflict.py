from __future__ import annotations

from typing import Any

from ashare.news.schema import normalize_direction


def _factor_weak(candidate: dict[str, Any] | None, key: str, threshold: float) -> bool:
    c = candidate or {}
    try:
        val = float(c.get(key) or (c.get("factors") or {}).get(key) or 0)
    except (TypeError, ValueError):
        val = 0.0
    return val < threshold


def _price_strong(candidate: dict[str, Any] | None) -> bool:
    c = candidate or {}
    pr = c.get("price_reaction") or {}
    if isinstance(pr, dict) and pr.get("available"):
        chg = pr.get("change_pct") or pr.get("return_1d")
        try:
            return float(chg or 0) > 0.02
        except (TypeError, ValueError):
            pass
    pir = str(c.get("price_in_risk") or "").upper()
    return pir in {"LOW", "NORMAL"}


def _news_dir(intel: dict[str, Any] | None, events: list[dict[str, Any]] | None = None) -> int:
    d = normalize_direction((intel or {}).get("direction") or (intel or {}).get("evidence_direction"))
    if d == "positive":
        return 1
    if d == "negative":
        return -1
    if d == "mixed":
        return 0
    for ev in events or []:
        ed = normalize_direction(ev.get("evidence_direction") or ev.get("direction"))
        if ed == "positive":
            return 1
        if ed == "negative":
            return -1
    return 0


def _quant_dir(candidate: dict[str, Any] | None, price_signal: str | None = None) -> int:
    c = candidate or {}
    try:
        leader = float(c.get("leader_score") or 0)
        cs = float(c.get("candidate_score") or 0)
        score = max(leader, cs)
    except (TypeError, ValueError):
        score = 0.0
    ps = str(price_signal or c.get("price_signal") or "").lower()
    try:
        rs = float(c.get("rs_score") or (c.get("factors") or {}).get("rs") or 0)
    except (TypeError, ValueError):
        rs = 0.0
    try:
        mom = float(c.get("momentum_score") or (c.get("factors") or {}).get("momentum") or 0)
    except (TypeError, ValueError):
        mom = 0.0
    vol_ok = not _factor_weak(c, "volume_confirm", 0.35)
    if ps in {"strong", "up", "bull"} or score >= 0.35 or (rs >= 0.4 and mom >= 0.3):
        return 1
    if ps in {"weak", "down", "bear"} or score <= 0.12 or (rs < 0.2 and mom < 0.15):
        return -1
    if vol_ok and _price_strong(c):
        return 1
    return 0


def _news_support_score(
    intelligence: dict[str, Any] | None,
    candidate: dict[str, Any] | None,
    *,
    news_threshold: float = 0.12,
) -> float:
    c = candidate or {}
    intel = intelligence or c.get("news_intelligence") or {}
    try:
        net = float(c.get("news_score") or 0)
    except (TypeError, ValueError):
        net = 0.0
    try:
        intel_score = float(c.get("news_intelligence_score") or intel.get("news_intelligence_score") or 0)
    except (TypeError, ValueError):
        intel_score = 0.0
    try:
        imp = float(intel.get("importance") or 0)
    except (TypeError, ValueError):
        imp = 0.0
    return max(net, intel_score, imp)


def compute_news_quant_conflict(
    *,
    intelligence: dict[str, Any] | None = None,
    events: list[dict[str, Any]] | None = None,
    candidate: dict[str, Any] | None = None,
    price_signal: str | None = None,
) -> dict[str, Any]:
    """0~1 news vs quant/price disagreement for AI routing only."""
    nd = _news_dir(intelligence, events)
    qd = _quant_dir(candidate, price_signal)
    c = candidate or {}
    rs_weak = _factor_weak(c, "rs_score", 0.25) and _factor_weak(c, "rs", 0.25)
    mom_weak = _factor_weak(c, "momentum_score", 0.2)
    vol_weak = _factor_weak(c, "volume_confirm", 0.35)
    price_strong = _price_strong(c)
    news_support = _news_support_score(intelligence, c)
    quant_strong = qd > 0 or float(c.get("leader_score") or c.get("candidate_score") or 0) >= 0.15

    if news_support < 0.12 and quant_strong and nd >= 0:
        score = 0.74
        reason = "news_weak_quant_strong"
    elif nd == 0 or qd == 0:
        score = 0.0
        reason = "insufficient_signals"
    elif nd == qd:
        if news_support < 0.12 and quant_strong:
            score = 0.68
            reason = "news_weak_quant_strong"
        else:
            score = 0.0
            reason = "aligned"
    else:
        score = 0.55
        if nd > 0 and qd < 0:
            reason = "news_positive_quant_weak"
            if rs_weak or mom_weak or vol_weak:
                score = 0.82
        elif nd < 0 and qd > 0:
            reason = "news_negative_price_strong"
            if price_strong:
                score = 0.78
        else:
            reason = "news_quant_disagreement"
            score = 0.65

    return {
        "news_conflict": bool(score > 0),
        "conflict_score": round(float(score), 4),
        "news_direction": nd,
        "quant_direction": qd,
        "reason": reason,
        "signals": {
            "rs_weak": rs_weak,
            "momentum_weak": mom_weak,
            "volume_weak": vol_weak,
            "price_strong": price_strong,
            "news_support": news_support,
        },
    }


def compute_news_conflict(
    *,
    intelligence: dict[str, Any] | None = None,
    events: list[dict[str, Any]] | None = None,
    candidate: dict[str, Any] | None = None,
    price_signal: str | None = None,
) -> dict[str, Any]:
    """Backward-compatible alias — delegates to enhanced quant conflict when candidate present."""
    if candidate:
        return compute_news_quant_conflict(
            intelligence=intelligence,
            events=events,
            candidate=candidate,
            price_signal=price_signal,
        )
    nd = _news_dir(intelligence, events)
    qd = _quant_dir(candidate, price_signal)
    if nd == 0 or qd == 0:
        return {
            "news_conflict": False,
            "conflict_score": 0.0,
            "news_direction": nd,
            "quant_direction": qd,
            "reason": "insufficient_signals",
        }
    if nd == qd:
        return {
            "news_conflict": False,
            "conflict_score": 0.0,
            "news_direction": nd,
            "quant_direction": qd,
            "reason": "aligned",
        }
    reason = "news_positive_quant_weak" if nd > 0 and qd < 0 else "news_negative_price_strong"
    return {
        "news_conflict": True,
        "conflict_score": 0.75,
        "news_direction": nd,
        "quant_direction": qd,
        "reason": reason,
    }
