from __future__ import annotations

from typing import Any

from ashare.config_loaders import load_yaml_config
from ashare.events import EventEngine
from ashare.factors.engine import FactorEngine
from ashare.leader.lifecycle import BUY_CANDIDATE, BUY_READY, FOCUS
from ashare.pool.builder import build_leader_pool
from ashare.profit import ProfitInflectionEngine
from ashare.research.hypothesis import ResearchHypothesisEngine
from ashare.symbols import to_symbol


def _pool_discovery_sources(row: dict[str, Any]) -> list[str]:
    tags: set[str] = set()
    raw = [str(x) for x in (row.get("sources") or [])]
    if row.get("source"):
        raw.append(str(row["source"]))
    for x in raw:
        if x in {"tech_leader"}:
            tags.add("quant")
        elif x in {"limit_up", "strong"}:
            tags.add("event")
        elif x in {"profit_gap", "yjyg"}:
            tags.add("profit")
    if float(row.get("profit_gap_score") or 0) > 0:
        tags.add("profit")
    if float(row.get("event_score") or 0) > 0.3 or (row.get("event_tags")):
        if any(t in str(row.get("event_tags")) for t in ("涨停", "强势", "预增", "预减")):
            tags.add("event")
    if (row.get("profit_inflection") or {}).get("available"):
        tags.add("profit")
    if not tags:
        tags.add("quant")
    return sorted(tags)


class CandidateEngine:
    """
    Funnel: pool (quant/event/profit) ∪ news discovery → dedup → rank → research universe.
    News is not fetched until after union ranking (Stock→News validation on Top-N only).
    Never sends full market to LLM. Never treats news as BUY.
    """

    def __init__(self, cfg: dict[str, Any] | None = None) -> None:
        self.cfg = cfg or {}
        self.research_cfg = load_yaml_config(self.cfg, "research")
        self.funnel = dict(self.research_cfg.get("funnel") or {})
        self.factors = FactorEngine(self.cfg)
        self.profit = ProfitInflectionEngine(self.cfg)
        self.events = EventEngine(self.cfg)

    def build_research_universe(
        self,
        panel: dict[str, Any] | None = None,
        *,
        pool: dict[str, Any] | None = None,
        news_discovery: dict[str, Any] | None = None,
        as_of: str | None = None,
    ) -> dict[str, Any]:
        pool = pool or build_leader_pool(self.cfg)
        ncfg = load_yaml_config(self.cfg, "news")
        cw = dict(ncfg.get("candidate_weights") or {})
        max_events = int(self.funnel.get("max_after_events", 100))
        max_union = int(self.funnel.get("max_union_candidates", 100))
        max_research = int(self.funnel.get("max_research_pool", 20))
        rejected: list[dict[str, Any]] = list((news_discovery or {}).get("rejected") or [])

        rows = []
        for c in pool.get("candidates") or []:
            sym = to_symbol(c.get("symbol"))
            if not sym:
                continue
            rows.append({**c, "symbol": sym})

        rows = self.profit.enrich_candidates(rows)
        rows = self.events.enrich_candidates(rows)
        filtered = []
        for r in rows:
            pi = r.get("profit_inflection") or {}
            if pi.get("quality") == "D" and float(r.get("event_score") or 0) < 0.3:
                rejected.append(
                    {
                        "symbol": r.get("symbol"),
                        "reject_reason": "FACTOR_VALIDATION_FAIL",
                        "candidate_sources": _pool_discovery_sources(r),
                    }
                )
                continue
            filtered.append(r)
        rows = filtered[:max_events]

        as_of_str = as_of or str((news_discovery or {}).get("as_of") or "")
        from ashare.leader import LeaderPipeline

        leader_pipe = LeaderPipeline(self.cfg)
        leader_pack: dict[str, Any] = {"rows": rows, "rejected": [], "focus_stats": {}}
        if leader_pipe.enabled and panel:
            leader_pack = leader_pipe.enrich_rows(rows, panel, as_of=as_of_str or "")
            rows = leader_pack["rows"]
            rejected.extend(leader_pack.get("rejected") or [])

        factor_rows: list[dict[str, Any]] = []
        if panel:
            factor_rows = self.factors.asof_rows(panel, as_of=as_of_str or None)
        by_f = {f["symbol"]: f for f in factor_rows}

        scored: list[dict[str, Any]] = []
        by_sym: dict[str, dict[str, Any]] = {}
        for r in rows:
            f = by_f.get(r["symbol"]) or {}
            leader = float(r.get("leader_score") or f.get("leader_score") or 0)
            pi_score = float((r.get("profit_inflection") or {}).get("score") or 0)
            ev_score = float(r.get("event_score") or 0)
            item = {
                **r,
                **{k: v for k, v in f.items() if k != "symbol"},
                "candidate_sources": _pool_discovery_sources(r),
                "news_score": 0.0,
                "candidate_score": 0.45 * leader + 0.35 * pi_score + 0.20 * ev_score,
                "trigger": self._trigger(r, leader, pi_score, ev_score),
                "in_council": bool(r.get("in_council")),
            }
            by_sym[r["symbol"]] = item
            scored.append(item)

        scored.sort(key=lambda x: x["candidate_score"], reverse=True)
        quant_top_n = {r["symbol"] for r in scored[:max_events]}

        panel = panel or {}
        from ashare.research.price_reaction import annotate_news_candidate_price

        for nc_raw in (news_discovery or {}).get("news_candidates") or []:
            if str(nc_raw.get("status") or "") == "REJECTED":
                rejected.append(dict(nc_raw))
                continue
            if str(nc_raw.get("discovery_grade") or "") == "INFERRED":
                rejected.append({**nc_raw, "reject_reason": "INFERRED_DISCOVERY"})
                continue
            if leader_pipe.enabled and leader_pipe.limit_up.reject_news_only(nc_raw):
                rejected.append({**nc_raw, "reject_reason": "NOT_LIMIT_UP_NEWS_ONLY"})
                continue
            try:
                sym = to_symbol(nc_raw.get("symbol"))
            except Exception:  # noqa: BLE001
                rejected.append({**nc_raw, "reject_reason": "NOT_ENOUGH_EVIDENCE"})
                continue
            df = panel.get(sym)
            if df is None or getattr(df, "empty", True):
                rejected.append({**nc_raw, "symbol": sym, "reject_reason": "FACTOR_VALIDATION_FAIL"})
                continue
            # Price-In: research warning only — never reject for HIGH price_in_risk
            nc = annotate_news_candidate_price(nc_raw, panel, as_of=as_of_str or None)
            last = df.iloc[-1]
            if bool(last.get("is_st")) or bool(last.get("is_halt")):
                rejected.append({**nc, "symbol": sym, "reject_reason": "RISK_FILTER"})
                continue
            news_proxy = float(nc.get("event_impact") or 0) * max(float(nc.get("confidence") or 0), 0.2)
            news_proxy = max(-1.0, min(1.0, news_proxy))
            hyps = list(nc.get("research_hypotheses") or [])
            if not hyps:
                hyps = [ResearchHypothesisEngine().from_event(nc).to_dict()]
            if sym in by_sym:
                item = by_sym[sym]
                srcs = set(item.get("candidate_sources") or [])
                srcs.add("news")
                item["candidate_sources"] = sorted(srcs)
                item["news_discovery"] = nc
                item["price_in_risk"] = nc.get("price_in_risk") or "UNKNOWN"
                item["news_score"] = max(float(item.get("news_score") or 0), news_proxy)
                item["research_hypotheses"] = hyps
            else:
                f = by_f.get(sym) or {}
                leader = float(f.get("leader_score") or 0)
                stub = {
                    "symbol": sym,
                    "name": nc.get("name") or f.get("name") or "",
                    "source": "news",
                    "sources": ["news"],
                    "candidate_sources": ["news"],
                    "thesis": nc.get("reason") or "",
                    "news_discovery": nc,
                    "price_in_risk": nc.get("price_in_risk") or "UNKNOWN",
                    "research_hypotheses": hyps,
                    "news_score": news_proxy,
                    "event_score": abs(news_proxy),
                    "profit_inflection": {"score": 0.0, "quality": "unavailable", "available": False},
                    **{k: v for k, v in f.items() if k != "symbol"},
                    "leader_score": leader,
                    "trigger": {
                        "type": "新闻发现",
                        "reason": nc.get("reason") or nc.get("event_type") or "",
                        "score": round(news_proxy, 4),
                    },
                    "in_council": False,
                }
                stub["candidate_score"] = 0.45 * leader + 0.20 * float(stub["event_score"])
                by_sym[sym] = stub
                scored.append(stub)

        for item in scored:
            if "news" in (item.get("candidate_sources") or []) and "新闻" not in str((item.get("trigger") or {}).get("type") or ""):
                tr = dict(item.get("trigger") or {})
                tr["type"] = ((tr.get("type") or "") + "+新闻").strip("+")
                item["trigger"] = tr

        from ashare.ml.candidate_ranking import (
            apply_ml_rank_scores,
            compute_candidate_score,
            resolve_ml_weight,
        )

        ml_weight = resolve_ml_weight(self.cfg, cw)
        ml_enabled = bool((self.research_cfg.get("ml_ranking") or {}).get("enabled", True))
        if panel and ml_enabled and scored:
            from ashare.ml.ranking import MLRankingEngine

            try:
                scored = MLRankingEngine(self.cfg).predict_rows(scored)
                scored = apply_ml_rank_scores(scored)
            except Exception:  # noqa: BLE001
                pass
        for item in scored:
            item["candidate_score"] = compute_candidate_score(item, cw, ml_weight=ml_weight)

        scored.sort(key=lambda x: x["candidate_score"], reverse=True)
        union = scored[:max_union]
        for item in scored[max_union:]:
            item["reject_reason"] = "RANKING_CUTOFF"
            rejected.append(
                {
                    "symbol": item.get("symbol"),
                    "reject_reason": "RANKING_CUTOFF",
                    "candidate_sources": item.get("candidate_sources"),
                    "candidate_score": item.get("candidate_score"),
                }
            )

        research = union[:max_research]
        research_syms = {r["symbol"] for r in research}
        # Focus / BUY_* must survive ranking cutoff (persistent monitoring).
        focus_keep = {
            FOCUS,
            BUY_CANDIDATE,
            BUY_READY,
        }
        for item in scored:
            sym = item.get("symbol")
            if not sym or sym in research_syms:
                continue
            lc = str(item.get("lifecycle") or "")
            if item.get("merged_from_focus") or lc in focus_keep or item.get("in_focus_watchlist"):
                research.append(item)
                research_syms.add(sym)
        for item in union[max_research:]:
            if item.get("symbol") in research_syms:
                continue
            item["reject_reason"] = "RANKING_CUTOFF"
            rejected.append(
                {
                    "symbol": item.get("symbol"),
                    "reject_reason": "RANKING_CUTOFF",
                    "candidate_sources": item.get("candidate_sources"),
                    "candidate_score": item.get("candidate_score"),
                }
            )

        from datetime import datetime as _dt
        from datetime import timezone as _tz

        from ashare.news.engine import NewsIntelligenceEngine

        news_eng = NewsIntelligenceEngine(self.cfg)
        as_of_dt = None
        if as_of_str:
            try:
                raw = str(as_of_str).replace("Z", "+00:00")
                as_of_dt = _dt.fromisoformat(raw)
                # date-only → end of day UTC so filter_asof keeps same-day news
                if len(raw.strip()) <= 10 and as_of_dt.tzinfo is None:
                    as_of_dt = _dt(
                        as_of_dt.year,
                        as_of_dt.month,
                        as_of_dt.day,
                        23,
                        59,
                        59,
                        tzinfo=_tz.utc,
                    )
                elif as_of_dt.tzinfo is None:
                    as_of_dt = as_of_dt.replace(tzinfo=_tz.utc)
            except Exception:  # noqa: BLE001
                as_of_dt = None
        for r in research:
            tier = str(r.get("news_tier") or "rules_only")
            skip_llm = False
            try:
                skip_llm = leader_pipe.should_skip_news_llm(r)
            except Exception:  # noqa: BLE001
                skip_llm = tier == "rules_only"
            if (tier == "rules_only" and not r.get("merged_from_focus")) or (
                skip_llm and not r.get("news_trigger")
            ):
                pkg = {
                    "news_data_incomplete": True,
                    "net_event_score": float(r.get("news_score") or 0),
                    "legacy_headlines": [],
                    "news_tier": tier,
                    "skipped_llm": True,
                }
                r["news_package"] = pkg
                r["news_data_incomplete"] = True
                r["compact_news"] = None
                continue
            try:
                pkg = news_eng.collect_stock(
                    r["symbol"],
                    name=str(r.get("name") or ""),
                    as_of=as_of_dt,
                    persist=True,
                )
            except Exception:  # noqa: BLE001
                pkg = {"news_data_incomplete": True, "net_event_score": 0.0, "legacy_headlines": []}
            r["news_package"] = pkg
            r["news_data_incomplete"] = bool(pkg.get("news_data_incomplete"))
            r["compact_news"] = pkg.get("compact_news_package")
            r["quant_top_n_at_signal"] = r["symbol"] in quant_top_n
            intel0 = (pkg.get("news_intelligence") or [None])[0] if pkg.get("news_intelligence") else None
            if intel0:
                r["news_intelligence"] = intel0
                r["news_intelligence_score"] = float(intel0.get("news_intelligence_score") or 0)
                r["evidence_direction"] = str(intel0.get("direction") or "unknown")
            net = float(pkg.get("net_event_score") or 0)
            if net:
                r["news_score"] = net
            from ashare.news.conflict import compute_news_conflict

            conflict = compute_news_conflict(
                intelligence=(pkg.get("news_intelligence") or [None])[0] if pkg.get("news_intelligence") else None,
                events=list(pkg.get("events") or []),
                candidate=r,
            )
            r["news_conflict"] = conflict
            r["conflict_score"] = float(conflict.get("conflict_score") or 0)
            if (r.get("news_discovery") or {}).get("news_role") == "discovery" and pkg.get("news_role") == "evidence":
                nd = dict(r.get("news_discovery") or {})
                nd["news_role"] = "both"
                r["news_discovery"] = nd
            r["candidate_score"] = compute_candidate_score(r, cw, ml_weight=ml_weight)
            tier = str(r.get("council_tier") or ("full" if r.get("in_council") else "scan"))
            r["in_council"] = tier == "full"
        research.sort(key=lambda x: x["candidate_score"], reverse=True)
        return {
            "pool_size": len(pool.get("candidates") or []),
            "after_events": len(rows),
            "n_union": len(union),
            "research_universe": research,
            "rejected": rejected[-300:],
            "sources": pool.get("sources"),
            "factor_version": self.factors.catalog.version,
            "research_symbols": sorted(research_syms),
            "quant_top_n_symbols": sorted(quant_top_n),
            "leader_pipeline": {
                "enabled": leader_pipe.enabled,
                "focus_stats": leader_pack.get("focus_stats"),
                "focus_watchlist": leader_pack.get("focus_watchlist"),
                "leader_rejected": len(leader_pack.get("rejected") or []),
                "dashboard": leader_pipe.dashboard_payload(research) if leader_pipe.enabled else {},
            },
        }

    def _trigger(self, row: dict[str, Any], leader: float, pi: float, ev: float) -> dict[str, Any]:
        bits = []
        if pi > 0.3:
            bits.append("利润断层")
        if ev > 0.3:
            bits.append("事件")
        if leader > 0.3:
            bits.append("板块/市场强度")
        return {
            "type": "+".join(bits) or "因子",
            "reason": (row.get("profit_inflection") or {}).get("reason") or row.get("thesis") or "",
            "score": round(0.45 * leader + 0.35 * pi + 0.20 * ev, 4),
        }
