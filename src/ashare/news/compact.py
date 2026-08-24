from __future__ import annotations

from typing import Any

from ashare.news.schema import normalize_direction

_MAJOR_TYPES = frozenset(
    {
        "order",
        "contract",
        "merger",
        "acquisition",
        "restructuring",
        "earnings",
        "earnings_preannouncement",
        "regulatory",
        "litigation",
    }
)


def _event_row(ev: dict[str, Any]) -> dict[str, Any]:
    return {
        k: ev.get(k)
        for k in (
            "event_id",
            "news_id",
            "event_type",
            "normalized_event_type",
            "direction",
            "evidence_direction",
            "impact_score",
            "news_intelligence_score",
            "title",
            "event_time",
        )
        if ev.get(k) is not None
    }


def _snippet(intel: dict[str, Any], *, max_len: int = 120) -> str:
    s = str(intel.get("summary") or "").strip()
    if not s:
        ev = intel.get("evidence") or []
        if ev:
            s = str(ev[0])
    return s[:max_len]


def build_compact_news_package(
    symbol: str,
    events: list[dict[str, Any]] | None,
    intel_rows: list[dict[str, Any]] | None,
    *,
    net_event_score: float = 0.0,
    conflicts: list[str] | None = None,
    max_snippet: int = 120,
    importance_threshold: float = 0.65,
) -> dict[str, Any]:
    """Structured news for Council — no raw headline dump."""
    evs = list(events or [])
    intel = list(intel_rows or [])
    positive: list[dict[str, Any]] = []
    negative: list[dict[str, Any]] = []
    top_evidence: list[dict[str, Any]] = []

    for row in intel:
        d = normalize_direction(row.get("direction") or row.get("evidence_direction"))
        imp = float(row.get("importance") or 0)
        et = str(row.get("event_type") or row.get("normalized_event_type") or "")
        item = {
            "news_id": row.get("news_id"),
            "event_type": et,
            "direction": d,
            "importance": imp,
            "news_intelligence_score": row.get("news_intelligence_score"),
            "evidence": (row.get("evidence") or [])[:3],
        }
        major = et in _MAJOR_TYPES or imp >= importance_threshold
        if major and _snippet(row, max_len=max_snippet):
            item["snippet"] = _snippet(row, max_len=max_snippet)
        if d == "positive":
            positive.append(item)
        elif d == "negative":
            negative.append(item)
        if row.get("evidence"):
            top_evidence.append(item)

    for ev in evs:
        ed = normalize_direction(ev.get("evidence_direction") or ev.get("direction"))
        if ed == "positive" and len(positive) < 6:
            positive.append(_event_row(ev))
        elif ed == "negative" and len(negative) < 6:
            negative.append(_event_row(ev))

    scores = [float(x.get("news_intelligence_score") or 0) for x in intel if x.get("news_intelligence_score")]
    best_score = max(scores) if scores else 0.0
    dirs = [normalize_direction(x.get("direction") or x.get("evidence_direction")) for x in intel]
    if dirs.count("positive") > dirs.count("negative"):
        evidence_dir = "positive"
    elif dirs.count("negative") > dirs.count("positive"):
        evidence_dir = "negative"
    elif "mixed" in dirs:
        evidence_dir = "mixed"
    else:
        evidence_dir = "neutral" if dirs else "unknown"

    return {
        "symbol": symbol,
        "events": [_event_row(e) for e in evs[:8]],
        "positive": positive[:6],
        "negative": negative[:6],
        "conflicts": list(conflicts or [])[:6],
        "top_evidence": top_evidence[:6],
        "news_intelligence_score": round(best_score, 4),
        "evidence_direction": evidence_dir,
        "net_event_score": round(float(net_event_score), 4),
    }
