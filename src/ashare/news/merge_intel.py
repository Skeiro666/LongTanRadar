from __future__ import annotations

from typing import Any

from ashare.news.models import ExtractedEvent
from ashare.news.schema import (
    _DIR_FROM_EXTRACT,
    _EVENT_FROM_EXTRACT,
    normalize_direction,
    normalize_event_type,
)


def _intel_subset(intel: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "event_type",
        "direction",
        "importance",
        "novelty",
        "market_relevance",
        "impact_horizon",
        "event_confidence",
        "summary",
        "evidence",
        "news_intelligence_score",
        "model_name",
        "prompt_version",
        "cache_hit",
        "status",
    )
    return {k: intel[k] for k in keys if k in intel}


def _dir_to_extract(d: str) -> tuple[str, float]:
    d = normalize_direction(d)
    if d == "positive":
        return "BULLISH", 0.65
    if d == "negative":
        return "BEARISH", -0.65
    if d == "mixed":
        return "NEUTRAL", 0.0
    return "NEUTRAL", 0.0


def merge_intelligence_into_events(
    events: list[ExtractedEvent],
    intel: dict[str, Any] | None,
    *,
    prefer_llm: bool = True,
) -> list[ExtractedEvent]:
    """Merge Task B intel into rule ExtractedEvents. Never blocks on LLM failure."""
    if not events:
        return events
    out: list[ExtractedEvent] = []
    intel = intel or {}
    has_intel = bool(intel.get("event_type") and intel.get("event_type") != "unknown")
    norm_type = normalize_event_type(intel.get("event_type")) if has_intel else ""

    for ev in events:
        ev.normalized_event_type = normalize_event_type(
            _EVENT_FROM_EXTRACT.get(ev.event_type, ev.event_type)
        )
        if not has_intel or not prefer_llm:
            ev.evidence_direction = normalize_direction(
                _DIR_FROM_EXTRACT.get(ev.direction, ev.direction.lower() if ev.direction else "unknown")
            )
            ev.intel_source = "rule"
            out.append(ev)
            continue

        ev.normalized_event_type = norm_type or ev.normalized_event_type
        ev.evidence_direction = normalize_direction(intel.get("direction"))
        ev.news_intelligence = _intel_subset(intel)
        ev.news_intelligence_score = float(intel.get("news_intelligence_score") or 0)
        ev.intel_source = "merged"

        d_label, d_score = _dir_to_extract(intel.get("direction") or "")
        if d_label != "NEUTRAL" or ev.direction == "NEUTRAL":
            ev.direction = d_label
            ev.direction_score = d_score

        imp = float(intel.get("importance") or 0)
        conf = float(intel.get("event_confidence") or 0)
        if imp > 0 or conf > 0:
            ev.impact_score = max(ev.impact_score, min(1.0, imp * 0.6 + conf * 0.4))
            ev.confidence = max(ev.confidence, conf)

        evidence = list(intel.get("evidence") or [])
        if evidence:
            ev.facts = evidence[:8]
        summary = str(intel.get("summary") or "").strip()
        if summary:
            ev.description = summary[:280]

        out.append(ev)
    return out
