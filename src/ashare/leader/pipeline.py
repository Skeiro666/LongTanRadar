from __future__ import annotations

import hashlib
import json
from typing import Any

import pandas as pd

from ashare.config_loaders import load_yaml_config
from ashare.leader.chase_risk import ChaseRiskEngine
from ashare.leader.features import compute_leader_features, limit_up_dates
from ashare.leader.focus_watchlist import FocusWatchlistStore
from ashare.leader.leader_ranking import LeaderRankingEngine
from ashare.leader.lifecycle import council_tier, news_tier
from ashare.leader.limit_up_universe import LimitUpUniverse
from ashare.leader.stage_engine import StageEngine
from ashare.leader.trade_timing import TradeTimingEngine
from ashare.symbols import to_symbol


def _state_hash(row: dict[str, Any]) -> str:
    key = {
        "stage": row.get("stage"),
        "chase": row.get("chase_score"),
        "timing": row.get("trade_timing_action"),
        "board": row.get("board_count"),
        "news": round(float(row.get("news_score") or 0), 3),
    }
    return hashlib.sha256(json.dumps(key, sort_keys=True).encode()).hexdigest()[:16]


class LeaderPipeline:
    """
    Limit-up leader research pipeline:
    LimitUpUniverse → LeaderRanking → Stage/Chase → Timing → Focus merge.
    """

    def __init__(self, cfg: dict[str, Any] | None = None) -> None:
        self.cfg = cfg or {}
        self.lc = load_yaml_config(self.cfg, "leader")
        self.limit_up = LimitUpUniverse(cfg)
        self.ranking = LeaderRankingEngine(cfg)
        self.stage = StageEngine(cfg)
        self.chase = ChaseRiskEngine(cfg)
        self.timing = TradeTimingEngine(cfg)
        self.focus = FocusWatchlistStore(cfg)

    @property
    def enabled(self) -> bool:
        return bool(self.lc.get("enabled", True))

    def enrich_rows(
        self,
        rows: list[dict[str, Any]],
        panel: dict[str, pd.DataFrame],
        *,
        as_of: str,
    ) -> dict[str, Any]:
        if not self.enabled:
            return {"rows": rows, "rejected": [], "focus_stats": {}, "feats_by_sym": {}}

        feats_by_sym: dict[str, dict[str, Any]] = {}
        for r in rows:
            sym = to_symbol(r.get("symbol") or "")
            df = panel.get(sym)
            if df is not None and not df.empty:
                feats_by_sym[sym] = compute_leader_features(df, as_of=as_of)
                feats_by_sym[sym].update(limit_up_dates(df, as_of=as_of))

        filtered, rejected = self.limit_up.filter_rows(rows, feats_by_sym=feats_by_sym)
        enriched: list[dict[str, Any]] = []
        for r in filtered:
            sym = to_symbol(r["symbol"])
            feats = feats_by_sym.get(sym) or {}
            r = {**r, **self.ranking.annotate(r, feats)}
            r.update(self.stage.annotate(r, feats))
            r.update(self.chase.annotate(feats, stage=r.get("stage")))
            neg = float(r.get("negative_evidence_score") or 0)
            if float(r.get("conflict_score") or 0) >= 0.65:
                neg = max(neg, 0.5)
            timing = self.timing.evaluate(
                leader_score=float(r.get("leader_score") or 0),
                factor_score=float(r.get("candidate_score") or r.get("leader_score") or 0),
                stage=str(r.get("stage") or "EARLY"),
                chase_score=float(r.get("chase_score") or 0),
                news_score=float(r.get("news_score") or 0),
                event_score=float(r.get("event_score") or 0),
                profit_score=float((r.get("profit_inflection") or {}).get("score") or 0),
                negative_evidence=neg,
                risk_score=1.0 if feats.get("limit_up_today") else 0.0,
                limit_up=bool(feats.get("limit_up_today")),
            )
            r.update(timing)
            r["negative_evidence_score"] = neg
            r["state_version"] = _state_hash(r)
            r["leader_features"] = feats
            lc = self.focus._initial_lifecycle(r)
            r["lifecycle"] = lc
            ct = council_tier(lc, self.lc)
            r["council_tier"] = ct
            r["news_tier"] = news_tier(lc, r.get("trade_timing_action"), self.lc)
            r["in_council"] = ct == "full"
            r["status_reason"] = timing.get("timing_reason")
            enriched.append(r)

        merged, focus_stats = self.focus.merge_cycle(enriched, as_of=as_of)
        for r in merged:
            lc = str(r.get("lifecycle") or "")
            r["council_tier"] = council_tier(lc, self.lc)
            r["news_tier"] = news_tier(lc, r.get("trade_timing_action"), self.lc)
            r["in_council"] = r["council_tier"] == "full" or bool(r.get("merged_from_focus"))

        merged.sort(
            key=lambda x: (
                x.get("lifecycle") in {"BUY_READY", "BUY_CANDIDATE", "FOCUS"},
                float(x.get("leader_score") or 0),
                int(x.get("board_count") or 0),
            ),
            reverse=True,
        )
        return {
            "rows": merged,
            "rejected": rejected,
            "focus_stats": focus_stats,
            "feats_by_sym": feats_by_sym,
            "focus_watchlist": self.focus.load(),
        }

    def should_skip_news_llm(self, row: dict[str, Any], *, payload_hash: str | None = None) -> bool:
        tier = str(row.get("news_tier") or "rules_only")
        if tier == "rules_only":
            return True
        prev = row.get("analysis_cache") or {}
        if payload_hash and prev.get("payload_hash") == payload_hash:
            return True
        if prev.get("state_version") == row.get("state_version"):
            return True
        return False

    def dashboard_payload(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        stage_perf: dict[str, list[float]] = {}
        board_perf: dict[str, list[float]] = {}
        for r in rows:
            st = str(r.get("stage") or "UNKNOWN")
            stage_perf.setdefault(st, []).append(float(r.get("trade_timing_score") or 0))
            b = int(r.get("board_count") or 0)
            bk = f"{min(b, 5)}+" if b >= 5 else str(b)
            board_perf.setdefault(bk, []).append(float(r.get("leader_score") or 0))
        return {
            "stage_performance": {
                k: {"n": len(v), "mean_timing": sum(v) / len(v) if v else None} for k, v in stage_perf.items()
            },
            "board_performance": {
                k: {"n": len(v), "mean_leader": sum(v) / len(v) if v else None} for k, v in board_perf.items()
            },
        }
