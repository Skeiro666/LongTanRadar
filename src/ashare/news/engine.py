from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ashare.config_loaders import load_yaml_config
from ashare.news.classify import classify_news
from ashare.news.dedup import dedupe_news
from ashare.news.expectation import expectation_gap
from ashare.news.extract import extract_events
from ashare.news.linking import link_entities
from ashare.news.models import ExtractedEvent, RawNews
from ashare.news.package import build_package, filter_asof
from ashare.news.provider import ProviderUnavailable
from ashare.news.registry import build_providers
from ashare.news.score import annotate_event, net_event_score
from ashare.news.store import NewsStore
from ashare.symbols import to_symbol

logger = logging.getLogger("ashare.news.engine")


class NewsIntelligenceEngine:
    """Independent of LLM: fetch → store → dedup → link → classify → extract → score."""

    def __init__(self, cfg: dict[str, Any] | None = None) -> None:
        self.cfg = cfg or {}
        self.news_cfg = load_yaml_config(self.cfg, "news")
        root = Path(self.cfg.get("_root") or Path(__file__).resolve().parents[2])
        self.store = NewsStore(root)
        timeout = float((self.news_cfg.get("fetch") or {}).get("timeout_sec") or 12)
        names = list(self.news_cfg.get("providers") or ["baidu", "eastmoney", "sina"])
        self.providers = build_providers(names, timeout_sec=timeout)
        self.version = str(self.news_cfg.get("news_version") or "news_v1")

    def collect_stock(
        self,
        symbol: str,
        *,
        name: str = "",
        as_of: datetime | None = None,
        persist: bool = True,
    ) -> dict[str, Any]:
        sym = to_symbol(symbol)
        limit = int((self.news_cfg.get("fetch") or {}).get("stock_limit") or 20)
        fetched: list[RawNews] = []
        statuses: list[str] = []
        incomplete = False
        for p in self.providers:
            try:
                batch = p.fetch_stock_news(sym, name=name, limit=limit)
                fetched.extend(batch)
                statuses.append(f"{p.name}=ok")
            except ProviderUnavailable as exc:
                incomplete = True
                statuses.append(f"{p.name}={exc.status}")
                logger.warning("provider %s unavailable: %s", p.name, exc)
        fetched = filter_asof(fetched, as_of)
        fetched = dedupe_news(fetched)
        if persist:
            self.store.append(fetched)

        min_link = float((self.news_cfg.get("fetch") or {}).get("min_link_confidence") or 0.5)
        linked: list[RawNews] = []
        weak_dropped: list[dict[str, Any]] = []
        events: list[ExtractedEvent] = []
        classifications: dict[str, str] = {}
        entities_out: list[dict[str, Any]] = []
        intel_client = None
        intel_engine = None
        try:
            from ashare.news.intelligence import LocalNewsIntelligence
            from ashare.news.llm_mapping import news_llm_client

            intel_client = news_llm_client(self.cfg)
            if intel_client is not None:
                intel_engine = LocalNewsIntelligence(self.cfg, intel_client)
        except Exception:  # noqa: BLE001
            intel_engine = None
        for n in fetched:
            ents = link_entities(n, symbol=sym, name=name)
            from ashare.news.entity_resolve import annotate_entity_source

            ents = [annotate_entity_source(e) for e in ents]
            conf = ents[0].confidence if ents else 0.0
            if conf < min_link:
                weak_dropped.append(
                    {
                        "news_id": n.id,
                        "title": n.title[:160],
                        "link_confidence": conf,
                        "link_source": ents[0].link_source if ents else "none",
                        "entity_source": getattr(ents[0], "entity_source", "") if ents else "unknown",
                        "source": n.source,
                    }
                )
                continue
            linked.append(n)
            entities_out.extend(e.to_dict() for e in ents)
            cat = classify_news(n)
            classifications[n.id] = cat
            intel_row = None
            if intel_engine is not None:
                from ashare.news.enrich import extract_for_news

                intel_row = extract_for_news(n, intel_engine, ents, classification=cat)
            for ev in extract_events(n, symbol=sym, relevance=conf):
                ev = annotate_event(ev, n, link_confidence=conf, classification=cat)
                gap = expectation_gap()
                ev.expectation_available = bool(gap["available"])
                ev.expectation_gap = gap["gap"]
                ev.expectation_note = gap["note"]
                events.append(ev)
            if intel_row:
                n.raw_payload = {**(n.raw_payload or {}), "news_intelligence": intel_row, "news_role": "evidence"}

        net = net_event_score(events)
        pkg = build_package(
            symbol=sym,
            name=name,
            news=linked,
            events=events,
            classifications=classifications,
            entities=entities_out,
            net_score=net,
            provider_status=";".join(statuses) or "none",
            incomplete=incomplete or not linked,
        )
        pkg["link_filter"] = {
            "min_confidence": min_link,
            "n_fetched": len(fetched),
            "n_linked": len(linked),
            "n_weak_dropped": len(weak_dropped),
            "weak_dropped_sample": weak_dropped[:8],
            "note": "仅保留标题含公司名/代码的新闻；正文列表命中(body_only)与 query_weak 均丢弃",
        }
        pkg["versions"] = {
            "news_data_version": self.version,
            "event_engine_version": self.news_cfg.get("event_engine_version"),
            "provider_version": self.news_cfg.get("provider_version"),
        }
        intel_rows = [
            {
                **(n.raw_payload.get("news_intelligence") or {}),
                "news_id": n.id,
                "news_role": "evidence",
                "evidence_direction": (n.raw_payload.get("news_intelligence") or {}).get("direction") or "unknown",
            }
            for n in linked
            if (n.raw_payload or {}).get("news_intelligence")
        ]
        pkg["news_intelligence"] = intel_rows
        pkg["news_role"] = "evidence"
        if intel_rows:
            from ashare.news.conflict import compute_news_conflict

            pkg["news_conflict"] = compute_news_conflict(
                intelligence=intel_rows[0],
                events=[e.to_dict() for e in events],
            )
        return pkg

    def collect_latest(
        self,
        *,
        as_of: datetime | None = None,
        persist: bool = True,
        limit: int | None = None,
        provider_names: list[str] | None = None,
    ) -> dict[str, Any]:
        """Market flash / roll news. No symbol required. Single-provider failure does not abort."""
        disc = dict(self.news_cfg.get("discovery") or {})
        names = list(provider_names or disc.get("providers") or ["sina", "ths"])
        timeout = float((self.news_cfg.get("fetch") or {}).get("timeout_sec") or 12)
        providers = build_providers(names, timeout_sec=timeout)
        nlimit = int(limit or (self.news_cfg.get("fetch") or {}).get("latest_limit") or 40)
        fetched: list[RawNews] = []
        statuses: list[str] = []
        incomplete = False
        for p in providers:
            try:
                batch = p.fetch_latest_news(limit=nlimit)
                fetched.extend(batch)
                statuses.append(f"{p.name}=ok:{len(batch)}")
            except ProviderUnavailable as exc:
                incomplete = True
                statuses.append(f"{p.name}={exc.status}")
                logger.warning("latest provider %s unavailable: %s", p.name, exc)
        fetched = filter_asof(fetched, as_of)
        fetched = dedupe_news(fetched)[:nlimit]
        if persist:
            self.store.append(fetched)
        return {
            "news": fetched,
            "n": len(fetched),
            "provider_status": ";".join(statuses) or "none",
            "news_data_incomplete": incomplete and not fetched,
            "incomplete_any": incomplete,
        }
