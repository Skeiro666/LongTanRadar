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
    }


@dataclass
class GateDecision:
    passed: bool
    reason: str
    rank: int = 0
    candidate_score: float = 0.0
    signals: dict[str, float] = field(default_factory=dict)
    boosted: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "reason": self.reason,
            "rank": self.rank,
            "candidate_score": self.candidate_score,
            "signals": self.signals,
            "boosted": self.boosted,
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
        return GateDecision(True, "gate_disabled", rank=rank, candidate_score=sig["candidate_score"], signals=sig)

    sig = _signal_values(candidate)
    cs = sig["candidate_score"]
    sources = set(candidate.get("candidate_sources") or [])
    boosted = bool(sources & set(gc["boost_sources"]))

    if rank < int(gc["always_pass_top_n"]):
        return GateDecision(
            True,
            f"always_pass_top_{gc['always_pass_top_n']}",
            rank=rank,
            candidate_score=cs,
            signals=sig,
            boosted=boosted,
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
        )

    strong = (
        sig["leader_score"] >= float(gc["min_leader_score"])
        or sig["ml_prediction"] >= float(gc["min_ml_prediction"])
        or sig["profit_score"] >= float(gc["min_profit_score"])
        or sig["event_score"] >= float(gc["min_event_score"])
        or sig["news_score"] >= float(gc["min_news_score"])
        or sig["hypothesis_count"] >= 1.0
    )
    if strong:
        return GateDecision(
            True,
            "SIGNAL_PASS",
            rank=rank,
            candidate_score=cs,
            signals=sig,
            boosted=boosted,
        )

    return GateDecision(
        False,
        "WEAK_SIGNALS",
        rank=rank,
        candidate_score=cs,
        signals=sig,
        boosted=boosted,
    )


@dataclass
class GateBatchResult:
    passed: list[dict[str, Any]]
    rejected: list[dict[str, Any]]
    decisions: dict[str, GateDecision]

    def summary(self) -> dict[str, Any]:
        reasons = {d.reason for d in self.decisions.values() if not d.passed}
        return {
            "n_in": len(self.passed) + len(self.rejected),
            "n_passed": len(self.passed),
            "n_rejected": len(self.rejected),
            "reject_reasons": {
                r: sum(1 for d in self.decisions.values() if d.reason == r and not d.passed) for r in reasons
            },
        }


def apply_research_gate(
    candidates: list[dict[str, Any]],
    cfg: dict[str, Any] | None = None,
) -> GateBatchResult:
    """Sort by candidate_score desc, evaluate gate, annotate rows."""
    ranked = sorted(candidates, key=lambda x: float(x.get("candidate_score") or 0), reverse=True)
    passed: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    decisions: dict[str, GateDecision] = {}

    for i, row in enumerate(ranked):
        sym = str(row.get("symbol") or "")
        dec = evaluate_research_gate(row, cfg, rank=i)
        decisions[sym] = dec
        annotated = {**row, "gate": dec.to_dict(), "in_council": dec.passed}
        if dec.passed:
            passed.append(annotated)
        else:
            annotated["reject_reason"] = dec.reason
            rejected.append(annotated)

    return GateBatchResult(passed=passed, rejected=rejected, decisions=decisions)
