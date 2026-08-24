from __future__ import annotations

from typing import Any

PROMPT_VERSION_ENTITY = "news_entity_v1"
PROMPT_VERSION_INTEL = "news_intel_v1"

ENTITY_SOURCES = (
    "explicit_code",
    "explicit_company",
    "alias",
    "fuzzy",
    "llm_inferred",
    "unknown",
)

NEWS_ROLES = ("discovery", "evidence", "both", "none")

DIRECTIONS = ("positive", "negative", "neutral", "mixed", "unknown")

HORIZONS = ("intraday", "short", "medium", "long", "unknown")

EVENT_TYPES = (
    "earnings",
    "earnings_preannouncement",
    "contract",
    "order",
    "merger",
    "acquisition",
    "restructuring",
    "share_buyback",
    "shareholder_reduction",
    "shareholder_increase",
    "executive_change",
    "dividend",
    "financing",
    "litigation",
    "regulatory",
    "product",
    "capacity",
    "policy",
    "industry",
    "supply_chain",
    "guidance",
    "other",
    "unknown",
)

DIRECT_ENTITY_SOURCES = frozenset({"explicit_code", "explicit_company", "alias"})
INFERRED_ENTITY_SOURCES = frozenset({"llm_inferred", "fuzzy"})

_LINK_TO_ENTITY_SOURCE = {
    "code": "explicit_code",
    "title_code": "explicit_code",
    "title+code": "explicit_code",
    "official_name": "explicit_company",
    "title_name": "explicit_company",
    "alias": "alias",
    "body_only": "fuzzy",
    "query_weak": "fuzzy",
    "llm_inference": "llm_inferred",
    "llm_inferred": "llm_inferred",
}

_EVENT_FROM_EXTRACT = {
    "EARNINGS_GUIDANCE": "earnings_preannouncement",
    "ORDER": "order",
    "PRICE_INCREASE": "product",
    "CAPACITY_EXPANSION": "capacity",
    "M_AND_A": "merger",
    "RESTRUCTURE": "restructuring",
    "SHARE_BUYBACK": "share_buyback",
    "INSIDER_SELL": "shareholder_reduction",
    "INSIDER_BUY": "shareholder_increase",
    "REGULATORY": "regulatory",
    "LITIGATION": "litigation",
    "POLICY_SUPPORT": "policy",
    "OTHER": "other",
}

_DIR_FROM_EXTRACT = {
    "VERY_BULLISH": "positive",
    "BULLISH": "positive",
    "NEUTRAL": "neutral",
    "BEARISH": "negative",
    "VERY_BEARISH": "negative",
}

_FORBIDDEN_TRADE_TOKENS = ("BUY", "SELL", "STRONG_BUY", "PASS", "WATCH", "仓位", "SMALL_POSITION")

HIGH_VALUE_CLASSIFICATIONS = frozenset(
    {
        "FINANCIAL",
        "ORDER",
        "REGULATORY",
        "POLICY",
        "M_AND_A",
        "SHARE_BUYBACK",
        "INSIDER_SELL",
        "INSIDER_BUY",
        "LITIGATION",
        "CAPACITY",
        "MANAGEMENT",
        "DIVIDEND",
        "COMPANY",
    }
)


def clamp01(v: Any, default: float = 0.0) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return default
    if x != x:  # NaN
        return default
    return max(0.0, min(1.0, x))


def normalize_entity_source(raw: str | None) -> str:
    s = str(raw or "").strip()
    if s in ENTITY_SOURCES:
        return s
    return _LINK_TO_ENTITY_SOURCE.get(s, "unknown")


def normalize_event_type(raw: str | None) -> str:
    s = str(raw or "").strip()
    if s in EVENT_TYPES:
        return s
    mapped = _EVENT_FROM_EXTRACT.get(s.upper() if s.isupper() or "_" in s else s, "")
    if mapped:
        return mapped
    low = s.lower().replace("-", "_").replace(" ", "_")
    if low in EVENT_TYPES:
        return low
    return "unknown"


def normalize_direction(raw: str | None) -> str:
    s = str(raw or "").strip().lower()
    if s in DIRECTIONS:
        return s
    mapped = _DIR_FROM_EXTRACT.get(str(raw or "").strip().upper(), "")
    return mapped or "unknown"


def normalize_horizon(raw: str | None) -> str:
    s = str(raw or "").strip().lower()
    aliases = {
        "short_term": "short",
        "medium_term": "medium",
        "long_term": "long",
        "near": "short",
    }
    s = aliases.get(s, s)
    return s if s in HORIZONS else "unknown"


def strip_trade_actions(text: str) -> str:
    out = str(text or "")
    for tok in _FORBIDDEN_TRADE_TOKENS:
        out = out.replace(tok, "")
    return out.strip()


def discovery_grade(entity_source: str) -> str:
    src = normalize_entity_source(entity_source)
    if src in DIRECT_ENTITY_SOURCES:
        return "DIRECT"
    if src in INFERRED_ENTITY_SOURCES:
        return "INFERRED"
    return "NONE"


# Compatibility aliases used by intelligence / tests
PROMPT_VERSION_ENTITY = PROMPT_VERSION_ENTITY
PROMPT_VERSION_INTEL = PROMPT_VERSION_INTEL
clamp01 = clamp01
normalize_entity_source = normalize_entity_source
normalize_event_type = normalize_event_type
normalize_horizon = normalize_horizon
strip_trade_actions = strip_trade_actions
discovery_grade = discovery_grade
HIGH_VALUE_CLASSIFICATIONS = HIGH_VALUE_CLASSIFICATIONS
