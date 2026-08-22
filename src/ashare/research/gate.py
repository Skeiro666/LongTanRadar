from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def _gate_cfg(cfg: dict[str, Any] | None) -> dict[str, Any]:
    if not cfg:
        return {"enabled": True}
    from ashare.config_loaders import load_yaml_config

    g = dict(load_yaml_config(cfg, "research").get("research_gate") or {})
    return {
        "enabled": bool(g.get("enabled", True)),
        "min_candidate_score": float(g.get("min_candidate_score") or 0.12),
        "min_leader_score": float(g.get("min_leader_score") or 0.10),
        "min_ml_prediction": float(g.get("min_ml_prediction") or 0.003),
        "min_profit_score": float(g.get("min_profit_score") or 0.15),
        "min_event_score": float(g.get("min_event_score") or 0.08),
        "min_news_score": float(g.get("min_news_score") or 0.12),
        "always_pass_top_n": int(g.get("always_pass_top_n") or 3),
        "boost_sources": list(g.get("boost_sources") or ["news", "profit", "event"]),
        "boost_score_floor": float(g.get("boost_score_floor") or 0.08),
        "deep_threshold": float(g.get("deep_threshold") or 0.22),
        "light_threshold": float(g.get("light_threshold") or 0.12),
        "max_deep": int(g.get("max_deep") or 10),
        "max_light": int(g.get("max_light") or 8),
        "max_llm_calls": int(g.get("max_llm_calls") or 30),
    }


@dataclass
class GateDecision:
    passed: bool
    reason: str
    rank: int = 0
    candidate_score: float = 0.0
    signals: dict[str, float] = field(default_factory=dict)
    boosted: bool = False
    research_tier: str = "NO_RESEARCH"

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "reason": self.reason,
            "rank": self.rank,
            "candidate_score": self.candidate_score,
            "signals": self.signals,
            "boosted": self.boosted,
            "research_tier": self.research_tier,
        }


def _signal_values(candidate: dict[str, Any]) -> dict[str, float]:
    pi = candidate.get("profit_inflection") or {}
    news = candidate.get("news_package") or {}
    hyps = candidate.get("research_hypotheses") or []
    return {
        "candidate_score": float(candidate.get("candidate_score") or 0),
        "leader_score": float(candidate.get("leader_score") or 0),
        "ml_prediction": float(candidate.get("ml_prediction") or 0),
        "profit_score": float(pi.get("score") or 0),
        "event_score": float(candidate.get("event_score") or (candidate.get("event") or {}).get("score") or 0),
        "news_score": float(candidate.get("news_score") or news.get("net_event_score") or 0),
        "hypothesis_count": float(len(hyps)),
    }


def _assign_tier(cs: float, gc: dict[str, Any]) -> str:
    if cs >= float(gc["deep_threshold"]):
        return "DEEP_RESEARCH"
    if cs >= float(gc["light_threshold"]):
        return "LIGHT_RESEARCH"
    return "NO_RESEARCH"


def evaluate_research_gate(
    candidate: dict[str, Any],
    cfg: dict[str, Any] | None = None,
    *,
    rank: int = 0,
) -> GateDecision:
    """
    Rule-only gate before council LLM. Top-N by candidate_score always pass.
    Others need minimum composite score plus at least one material signal.
    """
    gc = _gate_cfg(cfg)
    if not gc["enabled"]:
        sig = _signal_values(candidate)
        tier = _assign_tier(sig["candidate_score"], gc)
        return GateDecision(
            True, "gate_disabled", rank=rank, candidate_score=sig["candidate_score"], signals=sig, research_tier=tier
        )

    sig = _signal_values(candidate)
    cs = sig["candidate_score"]
    tier = _assign_tier(cs, gc)
    sources = set(candidate.get("candidate_sources") or [])
    boosted = bool(sources & set(gc["boost_sources"]))
    if tier == "NO_RESEARCH" and boosted and cs >= float(gc["boost_score_floor"]):
        tier = "LIGHT_RESEARCH"

    if rank < int(gc["always_pass_top_n"]):
        return GateDecision(
            True,
            f"always_pass_top_{gc['always_pass_top_n']}",
            rank=rank,
            candidate_score=cs,
            signals=sig,
            boosted=boosted,
            research_tier="DEEP_RESEARCH" if tier == "NO_RESEARCH" else tier,
        )

    score_floor = float(gc["boost_score_floor"]) if boosted else float(gc["min_candidate_score"])
    if cs < score_floor:
        return GateDecision(
            False,
            "LOW_CANDIDATE_SCORE",
            rank=rank,
            candidate_score=cs,
            signals=sig,
            boosted=boosted,
            research_tier=tier,
        )

    strong = (
        sig["leader_score"] >= float(gc["min_leader_score"])
        or sig["ml_prediction"] >= float(gc["min_ml_prediction"])
        or sig["profit_score"] >= float(gc["min_profit_score"])
        or sig["event_score"] >= float(gc["min_event_score"])
        or sig["news_score"] >= float(gc["min_news_score"])
        or sig["hypothesis_count"] >= 1.0
    )

    if tier == "NO_RESEARCH" and not strong:
        return GateDecision(
            False,
            "NO_RESEARCH_TIER",
            rank=rank,
            candidate_score=cs,
            signals=sig,
            boosted=boosted,
            research_tier=tier,
        )

    if strong:
        return GateDecision(
            True,
            "SIGNAL_PASS",
            rank=rank,
            candidate_score=cs,
            signals=sig,
            boosted=boosted,
            research_tier=tier if tier != "NO_RESEARCH" else "LIGHT_RESEARCH",
        )

    return GateDecision(
        False,
        "WEAK_SIGNALS",
        rank=rank,
        candidate_score=cs,
        signals=sig,
        boosted=boosted,
        research_tier=tier,
    )


@dataclass
class GateBatchResult:
    passed: list[dict[str, Any]]
    rejected: list[dict[str, Any]]
    decisions: dict[str, GateDecision]

    def summary(self) -> dict[str, Any]:
        reasons = {d.reason for d in self.decisions.values() if not d.passed}
        tiers: dict[str, int] = {}
        for d in self.decisions.values():
            tiers[d.research_tier] = tiers.get(d.research_tier, 0) + 1
        return {
            "n_in": len(self.passed) + len(self.rejected),
            "n_passed": len(self.passed),
            "n_rejected": len(self.rejected),
            "research_tiers": tiers,
            "reject_reasons": {
                r: sum(1 for d in self.decisions.values() if d.reason == r and not d.passed) for r in reasons
            },
        }


def apply_research_gate(
    candidates: list[dict[str, Any]],
    cfg: dict[str, Any] | None = None,
) -> GateBatchResult:
    """Sort by candidate_score desc, evaluate gate tiers, annotate rows."""
    gc = _gate_cfg(cfg)
    ranked = sorted(candidates, key=lambda x: float(x.get("candidate_score") or 0), reverse=True)
    passed: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    decisions: dict[str, GateDecision] = {}
    deep_n = 0
    light_n = 0

    for i, row in enumerate(ranked):
        sym = str(row.get("symbol") or "")
        dec = evaluate_research_gate(row, cfg, rank=i)
        if dec.passed:
            tier = dec.research_tier
            if tier == "DEEP_RESEARCH" and deep_n >= int(gc["max_deep"]):
                dec = GateDecision(
                    False,
                    "DEEP_BUDGET",
                    rank=i,
                    candidate_score=dec.candidate_score,
                    signals=dec.signals,
                    boosted=dec.boosted,
                    research_tier="NO_RESEARCH",
                )
            elif tier == "LIGHT_RESEARCH" and light_n >= int(gc["max_light"]):
                dec = GateDecision(
                    False,
                    "LIGHT_BUDGET",
                    rank=i,
                    candidate_score=dec.candidate_score,
                    signals=dec.signals,
                    boosted=dec.boosted,
                    research_tier="NO_RESEARCH",
                )
            elif dec.passed:
                if dec.research_tier == "DEEP_RESEARCH":
                    deep_n += 1
                elif dec.research_tier == "LIGHT_RESEARCH":
                    light_n += 1
        decisions[sym] = dec
        annotated = {**row, "gate": dec.to_dict(), "in_council": dec.passed, "research_tier": dec.research_tier}
        if dec.passed:
            passed.append(annotated)
        else:
            annotated["reject_reason"] = dec.reason
            rejected.append(annotated)

    return GateBatchResult(passed=passed, rejected=rejected, decisions=decisions)
