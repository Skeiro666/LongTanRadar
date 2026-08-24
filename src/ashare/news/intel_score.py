from __future__ import annotations

from typing import Any

from ashare.news.schema import clamp01


_QUALITY = {"A": 1.0, "B": 0.85, "C": 0.65, "D": 0.4}


def score_weights(news_cfg: dict[str, Any] | None) -> dict[str, float]:
    intel = dict((news_cfg or {}).get("intelligence") or {})
    w = dict(
        intel.get("score_weights")
        or {
            "importance": 0.22,
            "novelty": 0.18,
            "market_relevance": 0.22,
            "event_confidence": 0.16,
            "entity_confidence": 0.12,
            "source_quality": 0.10,
        }
    )
    return {k: float(v) for k, v in w.items()}


def news_intelligence_score(
    *,
    importance: float,
    novelty: float,
    market_relevance: float,
    event_confidence: float,
    entity_confidence: float,
    source_quality: str = "C",
    news_cfg: dict[str, Any] | None = None,
) -> float:
    """Programmatic score. LLM must not output this field."""
    w = score_weights(news_cfg)
    q = _QUALITY.get(str(source_quality or "C"), 0.5)
    parts = {
        "importance": clamp01(importance),
        "novelty": clamp01(novelty),
        "market_relevance": clamp01(market_relevance),
        "event_confidence": clamp01(event_confidence),
        "entity_confidence": clamp01(entity_confidence),
        "source_quality": q,
    }
    num = sum(w.get(k, 0.0) * parts[k] for k in parts)
    den = sum(w.values()) or 1.0
    return round(max(0.0, min(1.0, num / den)), 4)


news_intelligence_score = news_intelligence_score
