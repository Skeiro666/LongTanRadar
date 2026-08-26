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
from ashare.leader.lifecycle import council_tier, focus_tier, news_tier
from ashare.leader.limit_up_universe import LimitUpUniverse
from ashare.leader.reentry_engine import ReentryEngine
from ashare.leader.stage_engine import StageEngine
from ashare.leader.trade_timing import TradeTimingEngine
from ashare.symbols import to_symbol


def _state_hash(row: dict[str, Any]) -> str:
    key = {
        "stage": row.get("stage"),
        "chase": round(float(row.get("chase_score") or 0), 3),
        "timing": row.get("trade_timing_action"),
        "board": row.get("board_count"),
        "reentry": round(float(row.get("reentry_score") or 0), 3),
        "phase": row.get("reentry_phase"),
        "news": round(float(row.get("news_score") or 0), 3),
    }
    return hashlib.sha256(json.dumps(key, sort_keys=True).encode()).hexdigest()[:16]


def state_changed_materially(prev: dict[str, Any] | None, cur: dict[str, Any], cfg: dict[str, Any] | None = None) -> bool:
    """Event-driven refresh gate for Focus news/LLM."""
    if not prev:
        return True
    thr = dict((cfg or {}).get("refresh") or {})
    chase_delta = float(thr.get("chase_delta") or 0.12)
    reentry_delta = float(thr.get("reentry_delta") or 0.10)
    if str(prev.get("stage")) != str(cur.get("stage")):
        return True
    if int(prev.get("board_count") or 0) != int(cur.get("board_count") or 0):
        return True
    if bool(prev.get("limit_up_today")) != bool((cur.get("leader_features") or {}).get("limit_up_today")):
        return True
    if abs(float(prev.get("chase_score") or 0) - float(cur.get("chase_score") or 0)) >= chase_delta:
        return True
    if abs(float(prev.get("reentry_score") or 0) - float(cur.get("reentry_score") or 0)) >= reentry_delta:
        return True
    if str(prev.get("trade_timing_action")) != str(cur.get("trade_timing_action")):
        return True
    if str(cur.get("lifecycle")) in {"BUY_CANDIDATE", "BUY_READY"}:
        return True
    if str(cur.get("reentry_phase")) != str(prev.get("reentry_phase")):
        return True
    return False


class LeaderPipeline:
    """
    Limit-up leader research pipeline:
    LimitUpUniverse → LeaderRanking → Stage/Chase → Reentry → Timing → Focus merge.
    """

    def __init__(self, cfg: dict[str, Any] | None = None) -> None:
        self.cfg = cfg or {}
        self.lc = load_yaml_config(self.cfg, "leader")
        self.limit_up = LimitUpUniverse(cfg)
        self.ranking = LeaderRankingEngine(cfg)
        self.stage = StageEngine(cfg)
        self.chase = ChaseRiskEngine(cfg)
        self.reentry = ReentryEngine(cfg)
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
        prev_focus = self.focus.load()
        enriched: list[dict[str, Any]] = []
        for r in filtered:
            sym = to_symbol(r["symbol"])
            feats = feats_by_sym.get(sym) or {}
            df = panel.get(sym)
            r = {**r, **self.ranking.annotate(r, feats)}
            r.update(self.stage.annotate(r, feats))
            r.update(self.chase.annotate(feats, stage=r.get("stage")))
            neg = float(r.get("negative_evidence_score") or 0)
            if float(r.get("conflict_score") or 0) >= 0.65:
                neg = max(neg, 0.5)
            limit_up = bool(feats.get("limit_up_today"))
            re = self.reentry.annotate_from_bars(
                feats,
                df,
                stage=str(r.get("stage") or "EARLY"),
                chase_score=float(r.get("chase_score") or 0),
                news_score=float(r.get("news_score") or 0),
                negative_evidence=neg,
                limit_up=limit_up,
                as_of=as_of,
            )
            r.update(re)
            # merge pullback flat keys onto leader_features for debugging
            feats = {**feats, **(re.get("pullback_features") or {})}
            timing = self.timing.evaluate(
                leader_score=float(r.get("leader_score") or 0),
                factor_score=float(r.get("candidate_score") or r.get("leader_score") or 0),
                stage=str(r.get("stage") or "EARLY"),
                chase_score=float(r.get("chase_score") or 0),
                news_score=float(r.get("news_score") or 0),
                event_score=float(r.get("event_score") or 0),
                profit_score=float((r.get("profit_inflection") or {}).get("score") or 0),
                negative_evidence=neg,
                risk_score=1.0 if limit_up else 0.0,
                limit_up=limit_up,
                reentry_score=float(r.get("reentry_score") or 0),
                reentry_phase=str(r.get("reentry_phase") or "NONE"),
                board_count=int(r.get("board_count") or feats.get("consecutive_limit_up") or 0),
            )
            r.update(timing)
            r["negative_evidence_score"] = neg
            r["leader_features"] = feats
            r["state_version"] = _state_hash(r)
            prev = prev_focus.get(sym) or {}
            r["state_changed"] = state_changed_materially(prev, r, self.lc)
            r["news_trigger"] = bool(r["state_changed"]) or str(r.get("trade_timing_action")) in {
                "BUY_CANDIDATE",
                "BUY_READY",
            }
            lc = self.focus._initial_lifecycle(r)
            r["lifecycle"] = lc
            r["focus_tier"] = focus_tier(r, self.lc)
            r["entry_timeline"] = self._timeline(r)
            ct = council_tier(lc, self.lc)
            r["council_tier"] = ct
            r["news_tier"] = news_tier(lc, r.get("trade_timing_action"), self.lc)
            r["in_council"] = ct == "full"
            r["status_reason"] = ";".join(
                x for x in (timing.get("timing_reason"), re.get("reentry_reason")) if x
            )
            enriched.append(r)

        merged, focus_stats = self.focus.merge_cycle(enriched, as_of=as_of)
        for r in merged:
            lc = str(r.get("lifecycle") or "")
            r["council_tier"] = council_tier(lc, self.lc)
            r["news_tier"] = news_tier(lc, r.get("trade_timing_action"), self.lc)
            r["in_council"] = r["council_tier"] == "full" or bool(r.get("merged_from_focus"))
            r["focus_tier"] = focus_tier(r, self.lc)
            if not r.get("entry_timeline"):
                r["entry_timeline"] = self._timeline(r)

        merged.sort(
            key=lambda x: (
                x.get("lifecycle") in {"BUY_READY", "BUY_CANDIDATE", "FOCUS"},
                float(x.get("reentry_score") or 0),
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

    def _timeline(self, row: dict[str, Any]) -> list[dict[str, Any]]:
        stage_zh = {
            "EARLY": "早期",
            "TREND": "趋势",
            "ACCELERATION": "加速",
            "EXTREME": "极端",
            "DISTRIBUTION": "派发",
            "BREAKDOWN": "破位",
        }
        phase_zh = {
            "NONE": "无",
            "WAIT": "等待",
            "PULLBACK_WATCH": "回踩观察",
            "DIVERGENCE": "分歧",
            "STABILIZATION": "企稳",
            "REACCELERATION": "再加速",
            "BUY_CANDIDATE": "买点候选",
        }
        timing_zh = {
            "BUY_READY": "可买入",
            "BUY_CANDIDATE": "买点候选",
            "WAIT": "等待",
            "PASS": "放弃",
        }
        steps: list[dict[str, Any]] = []
        board = int(row.get("board_count") or 0)
        if board:
            steps.append({"event": f"{board}板", "detail": f"龙头分={row.get('leader_score')}"})
        st = str(row.get("stage") or "")
        if st:
            steps.append(
                {
                    "event": stage_zh.get(st, st),
                    "detail": f"追涨风险={row.get('chase_score')}",
                }
            )
        if st == "EXTREME":
            steps.append({"event": "等待", "detail": "极端阶段，不追高"})
        phase = str(row.get("reentry_phase") or "NONE")
        if phase and phase not in {"NONE", "WAIT"}:
            steps.append(
                {
                    "event": phase_zh.get(phase, phase),
                    "detail": f"再入场分={row.get('reentry_score')}",
                }
            )
        ta = str(row.get("trade_timing_action") or "")
        if ta:
            steps.append(
                {
                    "event": timing_zh.get(ta, ta),
                    "detail": row.get("status_reason") or row.get("timing_reason"),
                }
            )
        return steps

    def should_skip_news_llm(self, row: dict[str, Any], *, payload_hash: str | None = None) -> bool:
        tier = str(row.get("news_tier") or "rules_only")
        if tier == "rules_only":
            return True
        if row.get("news_trigger") is False and not row.get("state_changed", True):
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
        reentry_perf: dict[str, list[float]] = {}
        for r in rows:
            st = str(r.get("stage") or "UNKNOWN")
            stage_perf.setdefault(st, []).append(float(r.get("trade_timing_score") or 0))
            b = int(r.get("board_count") or 0)
            bk = f"{min(b, 5)}+" if b >= 5 else str(b)
            board_perf.setdefault(bk, []).append(float(r.get("leader_score") or 0))
            ph = str(r.get("reentry_phase") or "NONE")
            reentry_perf.setdefault(ph, []).append(float(r.get("reentry_score") or 0))
        return {
            "stage_performance": {
                k: {"n": len(v), "mean_timing": sum(v) / len(v) if v else None} for k, v in stage_perf.items()
            },
            "board_performance": {
                k: {"n": len(v), "mean_leader": sum(v) / len(v) if v else None} for k, v in board_perf.items()
            },
            "reentry_performance": {
                k: {"n": len(v), "mean_reentry": sum(v) / len(v) if v else None} for k, v in reentry_perf.items()
            },
        }
