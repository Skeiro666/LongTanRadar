from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ashare.config_loaders import load_yaml_config
from ashare.data.names import load_name_map
from ashare.news.classify import classify_news
from ashare.news.dedup import dedupe_news
from ashare.news.engine import NewsIntelligenceEngine
from ashare.news.extract import extract_events
from ashare.news.linking import link_entities_open
from ashare.news.models import ExtractedEvent, NewsCandidate, RawNews
from ashare.news.score import annotate_event

logger = logging.getLogger("ashare.news.opportunity")


class NewsOpportunityEngine:
    """
    Parallel news discovery: latest headlines → rule events → optional code-mapped NewsCandidate.
    Does not rank the quant pool and never emits BUY / orders.
    """

    def __init__(self, cfg: dict[str, Any] | None = None) -> None:
        self.cfg = cfg or {}
        self.news_cfg = load_yaml_config(self.cfg, "news")
        self.intel = NewsIntelligenceEngine(self.cfg)
        root = Path(self.cfg.get("_root") or Path(__file__).resolve().parents[2])
        self.out_path = root / "data" / "news" / "discovery_latest.json"

    def discover(
        self,
        *,
        as_of: datetime | None = None,
        persist: bool = True,
        news: list[RawNews] | None = None,
        name_map: dict[str, str] | None = None,
        aliases: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        disc = dict(self.news_cfg.get("discovery") or {})
        if not bool(disc.get("enabled", True)) and news is None:
            return self._empty(reason="disabled")

        incomplete = False
        provider_status = "injected"
        if news is None:
            try:
                latest = self.intel.collect_latest(as_of=as_of, persist=persist)
            except Exception as exc:  # noqa: BLE001
                logger.warning("news discovery fetch failed: %s", exc)
                return self._empty(reason="PROVIDER_UNAVAILABLE", error=str(exc)[:300])
            news = list(latest.get("news") or [])
            incomplete = bool(latest.get("incomplete_any") or latest.get("news_data_incomplete"))
            provider_status = str(latest.get("provider_status") or "")

        news = dedupe_news(list(news or []))
        max_c = int(disc.get("max_news_candidates") or 100)
        names = name_map if name_map is not None else load_name_map(self.cfg)
        als = aliases if aliases is not None else dict(disc.get("aliases") or {})
        industry_available = bool(disc.get("industry_map_available", False))
        from ashare.research.hypothesis import ResearchHypothesisEngine
        from ashare.news.cluster import cluster_timeline_events
        from ashare.news.evidence_registry import EvidenceRegistry

        hypo_eng = ResearchHypothesisEngine()
        registry = EvidenceRegistry(self.cfg)

        use_llm = bool(disc.get("llm_mapping", False))
        news_client = None
        if use_llm:
            from ashare.news.llm_mapping import news_llm_client

            news_client = news_llm_client(self.cfg)

        events: list[ExtractedEvent] = []
        candidates: list[NewsCandidate] = []
        rejected: list[dict[str, Any]] = []

        for n in news:
            cat = classify_news(n)
            ents = link_entities_open(n, name_map=names, aliases=als)
            if not ents and news_client is not None:
                from ashare.news.llm_mapping import infer_entities_from_news

                ents = infer_entities_from_news(n, news_client)
            extracted = extract_events(
                n,
                symbol=ents[0].symbol if ents else "",
                relevance=ents[0].confidence if ents else 0.35,
            )
            for ev in extracted:
                link_conf = ents[0].confidence if ents else 0.0
                ev = annotate_event(ev, n, link_confidence=link_conf, classification=cat)
                events.append(ev)
                if not ents:
                    reason = "INDUSTRY_MAP_UNAVAILABLE" if (
                        (not industry_available) and ("行业" in n.title or cat == "POLICY")
                    ) else "NOT_ENOUGH_EVIDENCE"
                    rejected.append(
                        {
                            "event_id": ev.event_id,
                            "event_type": ev.event_type,
                            "title": n.title,
                            "reject_reason": reason,
                            "mapping_method": "none",
                            "mapping_status": "unavailable",
                            "evidence_ids": [n.id],
                        }
                    )
                    continue
                for ent in ents:
                    method = ent.mapping_method or ent.link_source or "none"
                    ev_dict = ev.to_dict()
                    ekey = EvidenceRegistry.evidence_key(n.id, n.title)
                    evidence_id = registry.register(
                        key=ekey,
                        title=n.title,
                        source=n.source,
                        url=n.url,
                        published_at=n.published_at,
                        news_id=n.id,
                        symbol=ent.symbol,
                        persist=persist,
                    )
                    ev_dict["evidence_id"] = evidence_id
                    ev_dict["symbol"] = ent.symbol
                    hyp_obj = hypo_eng.from_event(ev, news=n)
                    hyp = hyp_obj.to_dict(ev)
                    inv_hyp = hyp_obj.to_investment_hypothesis(ev)
                    news_score = float(ev.impact_score) * max(float(ent.confidence), 0.2)
                    cand = NewsCandidate(
                        symbol=ent.symbol,
                        candidate_source="news",
                        candidate_sources=["news"],
                        event_id=ev.event_id,
                        news_event_id=ev.event_id,
                        event_type=ev.event_type,
                        event_direction=ev.direction,
                        direction=ev.direction,
                        event_impact=float(ev.impact_score),
                        news_score=news_score,
                        relevance_score=float(ev.relevance),
                        novelty_score=None,
                        novelty=None,
                        novelty_available=False,
                        source_quality=str(ev.source_quality or "C"),
                        confidence=float(ent.confidence),
                        time_horizon=ev.time_horizon,
                        price_reaction={"available": False, "note": "awaiting_bars"},
                        price_in_risk="UNKNOWN",
                        reason=n.title[:180],
                        evidence_ids=[evidence_id, n.id, ev.event_id],
                        research_hypotheses=[hyp],
                        investment_hypothesis=inv_hyp,
                        related_symbols=[ent.symbol],
                        mapping_method=method,
                        status="REJECTED" if method == "llm_inference" else "DISCOVERED",
                        lifecycle_status="NEW",
                        lifecycle_reason="fresh_discovery",
                        reject_reason="LOW_CONFIDENCE" if method == "llm_inference" else "",
                    )
                    if method == "llm_inference":
                        rejected.append(cand.to_dict())
                    else:
                        candidates.append(cand)

        # one candidate per symbol+event_type (keep higher confidence)
        uniq: dict[tuple[str, str], NewsCandidate] = {}
        for c in candidates:
            key = (c.symbol, c.event_type)
            prev = uniq.get(key)
            if prev is None or c.confidence > prev.confidence:
                uniq[key] = c
        candidates = sorted(uniq.values(), key=lambda x: x.confidence * (0.5 + abs(x.event_impact)), reverse=True)
        overflow = candidates[max_c:]
        for c in overflow:
            c.status = "REJECTED"
            c.reject_reason = "RANKING_CUTOFF"
            rejected.append(c.to_dict())
        candidates = candidates[:max_c]

        event_clusters = cluster_timeline_events(
            [e.to_dict() for e in events],
            max_clusters=int(disc.get("max_event_clusters") or 40),
            by_symbol=True,
        )

        payload = {
            "as_of": as_of.isoformat() if as_of else datetime.now(timezone.utc).isoformat(),
            "available": True,
            "news_data_incomplete": incomplete,
            "provider_status": provider_status,
            "n_news": len(news),
            "n_events": len(events),
            "n_event_clusters": len(event_clusters),
            "n_candidates": len(candidates),
            "n_rejected": len(rejected),
            "events": [e.to_dict() for e in events],
            "event_clusters": event_clusters,
            "news_candidates": [c.to_dict() for c in candidates],
            "rejected": rejected[:200],
            "note": "NewsCandidate is discovery only — not a trading action.",
        }
        if persist:
            try:
                self.out_path.parent.mkdir(parents=True, exist_ok=True)
                self.out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
            except Exception as exc:  # noqa: BLE001
                logger.warning("persist discovery failed: %s", exc)
        return payload

    def _empty(self, *, reason: str, error: str = "") -> dict[str, Any]:
        return {
            "as_of": datetime.now(timezone.utc).isoformat(),
            "available": False,
            "news_data_incomplete": True,
            "provider_status": reason,
            "n_news": 0,
            "n_events": 0,
            "n_candidates": 0,
            "n_rejected": 0,
            "events": [],
            "news_candidates": [],
            "rejected": [],
            "error": error,
            "note": "News discovery unavailable; quant/event/profit path must continue.",
        }

    def load_latest(self) -> dict[str, Any] | None:
        if not self.out_path.exists():
            return None
        try:
            return json.loads(self.out_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return None
