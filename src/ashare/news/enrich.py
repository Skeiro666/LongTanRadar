from __future__ import annotations

from typing import Any

from ashare.news.funnel import is_high_value_news
from ashare.news.intelligence import LocalNewsIntelligence
from ashare.news.models import NewsEntity, RawNews
from ashare.news.schema import DIRECT_ENTITY_SOURCES, INFERRED_ENTITY_SOURCES, normalize_entity_source


TRADE_TOKENS = ("BUY", "SELL", "STRONG_BUY", "仓位", "PASS")


def sanitize_no_trade(payload: dict[str, Any]) -> dict[str, Any]:
    blob = str(payload)
    for tok in TRADE_TOKENS:
        if tok in blob:
            payload["summary"] = str(payload.get("summary") or "").replace(tok, "")
            payload["hypothesis"] = str(payload.get("hypothesis") or "").replace(tok, "")
    payload.pop("action", None)
    payload.pop("rating", None)
    payload.pop("position", None)
    return payload


def entity_source_of(ent: NewsEntity) -> str:
    return getattr(ent, "entity_source", "") or normalize_entity_source(ent.mapping_method or ent.link_source)


def is_direct_entity(ent: NewsEntity) -> bool:
    return entity_source_of(ent) in DIRECT_ENTITY_SOURCES


def is_inferred_entity(ent: NewsEntity) -> bool:
    return entity_source_of(ent) in INFERRED_ENTITY_SOURCES


def extract_for_news(
    news: RawNews,
    engine: LocalNewsIntelligence | None,
    ents: list[NewsEntity],
    *,
    classification: str,
) -> dict[str, Any] | None:
    """Task B: intelligence. Runs on high-value news even if rules already mapped a symbol."""
    if engine is None or not engine.available:
        return None
    if not is_high_value_news(news, classification):
        return None
    ent = ents[0] if ents else None
    intel = engine.extract_intelligence(
        news,
        symbol=ent.symbol if ent else "",
        entity_confidence=float(ent.confidence) if ent else 0.0,
    )
    return sanitize_no_trade(intel)


def hypothesis_from_intel(intel: dict[str, Any] | None, news: RawNews) -> dict[str, Any]:
    if not intel:
        return {}
    hyp = str(intel.get("hypothesis") or "").strip()
    industries = list(intel.get("beneficiary_industries") or [])
    if not hyp and not industries:
        return {}
    return {
        "hypothesis": hyp or news.title[:120],
        "beneficiary_industries": industries,
        "confidence": min(0.68, float(intel.get("event_confidence") or 0.4)),
        "note": "hypothesis_only — not a candidate and not a trade action",
    }
