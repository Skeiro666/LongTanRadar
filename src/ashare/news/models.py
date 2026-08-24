from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def make_id(prefix: str) -> str:
    return f"{prefix}{utc_now().strftime('%Y%m%d')}{uuid4().hex[:8].upper()}"


def normalize_title(title: str) -> str:
    t = re.sub(r"</?em>", "", title or "")
    t = re.sub(r"\s+", "", t)
    t = t.lower()
    return t


def title_hash(title: str) -> str:
    return hashlib.sha256(normalize_title(title).encode("utf-8")).hexdigest()[:32]


@dataclass
class RawNews:
    id: str
    source: str
    title: str
    fetched_at: str
    source_id: str = ""
    url: str = ""
    content: str = ""
    summary: str = ""
    published_at: str = ""
    author: str = ""
    category: str = ""
    language: str = "zh"
    media: str = ""
    title_hash: str = ""
    query_symbol: str = ""
    query_name: str = ""
    provider_status: str = "ok"
    raw_payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class NewsEntity:
    news_id: str
    entity_type: str  # stock | industry | theme
    symbol: str = ""
    name: str = ""
    confidence: float = 0.0
    link_source: str = ""  # title | content | code | query_weak | official_name | alias | llm_inference
    mapping_method: str = ""
    entity_source: str = ""  # explicit_code | explicit_company | alias | fuzzy | llm_inferred | unknown

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ExtractedEvent:
    event_id: str
    news_id: str
    symbol: str
    event_type: str
    title: str
    description: str
    event_time: str
    discovery_time: str
    source: str
    source_url: str
    direction: str
    direction_score: float
    impact_score: float
    confidence: float
    time_horizon: str
    source_quality: str = "C"
    relevance: float = 0.0
    freshness: float = 0.0
    news_priority: float = 0.0
    expectation_gap: float | None = None
    expectation_available: bool = False
    expectation_note: str = "无一致预期数据，未伪造"
    facts: list[str] = field(default_factory=list)
    inferences: list[str] = field(default_factory=list)
    evidence_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class NewsCandidate:
    """Discovery output. Must never be treated as a BUY/order."""

    symbol: str
    candidate_source: str = "news"
    candidate_sources: list[str] = field(default_factory=lambda: ["news"])
    event_id: str = ""
    news_event_id: str = ""
    event_type: str = "OTHER"
    event_direction: str = "NEUTRAL"
    direction: str = "NEUTRAL"
    event_impact: float = 0.0
    news_score: float = 0.0
    relevance_score: float = 0.0
    novelty_score: float | None = None
    novelty: float | None = None
    novelty_available: bool = False
    source_quality: str = "C"
    confidence: float = 0.0
    time_horizon: str = "SHORT_TERM"
    price_reaction: dict[str, Any] = field(default_factory=lambda: {"available": False})
    price_in_risk: str = "UNKNOWN"
    price_in_score: float = 0.0
    lifecycle_status: str = "NEW"
    lifecycle_reason: str = ""
    reason: str = ""
    evidence_ids: list[str] = field(default_factory=list)
    research_hypotheses: list[dict[str, Any]] = field(default_factory=list)
    investment_hypothesis: dict[str, Any] = field(default_factory=dict)
    related_symbols: list[str] = field(default_factory=list)
    mapping_method: str = "none"
    entity_source: str = "unknown"
    discovery_grade: str = "NONE"
    news_role: str = "none"
    news_intelligence: dict[str, Any] = field(default_factory=dict)
    news_intelligence_score: float = 0.0
    news_conflict: dict[str, Any] = field(default_factory=dict)
    evidence_direction: str = "unknown"
    hypothesis: dict[str, Any] = field(default_factory=dict)
    status: str = "DISCOVERED"
    reject_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["direction"] = d.get("event_direction") or d.get("direction") or "NEUTRAL"
        d["novelty"] = d.get("novelty_score") if d.get("novelty") is None else d.get("novelty")
        if not d.get("news_event_id"):
            d["news_event_id"] = d.get("event_id") or ""
        if not d.get("news_score"):
            d["news_score"] = float(d.get("event_impact") or 0) * max(float(d.get("confidence") or 0), 0.2)
        return d


def dump_json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2, default=str)
