"""Research gate: hard floors + soft signals; missing ≠ 0 ≠ rejection evidence."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ashare.research.signal_contract import (
    attach_signal_contract,
    extract_candidate_signals,
    meets_threshold,
    numeric_or_none,
)


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
        # Soft: unavailable signals do not fail the OR; they only fail if hard_require_*
        "hard_require_ml": bool(g.get("hard_require_ml", False)),
        "hard_require_profit": bool(g.get("hard_require_profit", False)),
        "hard_require_event": bool(g.get("hard_require_event", False)),
        "hard_require_news": bool(g.get("hard_require_news", False)),
    }


@dataclass
class GateDecision:
    passed: bool
    reason: str
    rank: int = 0
    candidate_score: float = 0.0
    signals: dict[str, Any] = field(default_factory=dict)
    boosted: bool = False
    research_tier: str = "NO_RESEARCH"
    reject_codes: list[str] = field(default_factory=list)
    data_quality: str = "PARTIAL"

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "reason": self.reason,
            "rank": self.rank,
            "candidate_score": self.candidate_score,
            "signals": self.signals,
            "boosted": self.boosted,
            "research_tier": self.research_tier,
            "reject_codes": list(self.reject_codes),
            "data_quality": self.data_quality,
        }


def _signal_values(candidate: dict[str, Any]) -> dict[str, Any]:
    """
    Backward-compatible numeric view for routing/audit.
    Missing/unavailable → None (never coerced to 0).
    Also embeds _status map for consumers that need availability.
    """
    bundle = extract_candidate_signals(candidate)
    out: dict[str, Any] = {}
    statuses: dict[str, str] = {}
    for k, sig in bundle.items():
        statuses[k] = str(sig.get("status") or "MISSING")
        out[k] = numeric_or_none(sig)
    # Display-friendly: keep None for missing; routing may treat None as inactive
    out["_status"] = statuses
    out["_bundle"] = bundle
    return out


def _display_signals(sig: dict[str, Any]) -> dict[str, Any]:
    """Serialize for gate payload without inventing zeros."""
    skip = {"_status", "_bundle"}
    return {k: v for k, v in sig.items() if k not in skip}


def _assign_tier(cs: float | None, gc: dict[str, Any]) -> str:
    c = float(cs or 0.0)
    if c >= float(gc["deep_threshold"]):
        return "DEEP_RESEARCH"
    if c >= float(gc["light_threshold"]):
        return "LIGHT_RESEARCH"
    return "NO_RESEARCH"


def _strong_signal_pass(bundle: dict[str, Any], gc: dict[str, Any]) -> tuple[bool, list[str]]:
    """At least one available soft signal meets its threshold, or hypotheses present."""
    codes: list[str] = []
    checks = [
        ("leader_score", "min_leader_score", "LOW_LEADER_SCORE", "MISSING_LEADER_SCORE"),
        ("ml_prediction", "min_ml_prediction", "ML_BELOW_THRESHOLD", "MISSING_ML_DATA"),
        ("profit_score", "min_profit_score", "PROFIT_BELOW_THRESHOLD", "MISSING_PROFIT_DATA"),
        ("event_score", "min_event_score", "EVENT_BELOW_THRESHOLD", "MISSING_EVENT_DATA"),
        ("news_score", "min_news_score", "NEWS_BELOW_THRESHOLD", "MISSING_NEWS_DATA"),
    ]
    hard_map = {
        "ml_prediction": "hard_require_ml",
        "profit_score": "hard_require_profit",
        "event_score": "hard_require_event",
        "news_score": "hard_require_news",
    }
    any_pass = False
    for name, min_key, below_code, miss_code in checks:
        sig = bundle.get(name) or {}
        hard = bool(gc.get(hard_map.get(name, ""), False))
        if not sig.get("available"):
            if hard:
                codes.append(miss_code)
            continue
        if meets_threshold(sig, float(gc[min_key])):
            any_pass = True
        elif hard:
            codes.append(below_code)

    hyp = bundle.get("hypothesis_count") or {}
    if numeric_or_none(hyp) and float(numeric_or_none(hyp) or 0) >= 1.0:
        any_pass = True

    if hard_map and any(gc.get(v) for v in hard_map.values()) and codes and not any_pass:
        return False, codes
    return any_pass, codes


def evaluate_research_gate(
    candidate: dict[str, Any],
    cfg: dict[str, Any] | None = None,
    *,
    rank: int = 0,
) -> GateDecision:
    """
    Rule-only gate before council LLM. Top-N by candidate_score always pass.
    Others need minimum composite score plus at least one material *available* signal.
    Missing data never counts as a zero that satisfies or falsifies a soft threshold.
    """
    attach_signal_contract(candidate)
    gc = _gate_cfg(cfg)
    sig = _signal_values(candidate)
    bundle = sig.get("_bundle") or extract_candidate_signals(candidate)
    dq = str(candidate.get("data_quality") or "PARTIAL")
    cs = numeric_or_none(bundle.get("candidate_score") or {})
    cs_f = float(cs or 0.0)
    tier = _assign_tier(cs, gc)
    disp = _display_signals(sig)

    if not gc["enabled"]:
        return GateDecision(
            True,
            "gate_disabled",
            rank=rank,
            candidate_score=cs_f,
            signals=disp,
            research_tier=tier,
            data_quality=dq,
        )

    sources = set(candidate.get("candidate_sources") or [])
    boosted = bool(sources & set(gc["boost_sources"]))
    if tier == "NO_RESEARCH" and boosted and cs_f >= float(gc["boost_score_floor"]):
        tier = "LIGHT_RESEARCH"

    if rank < int(gc["always_pass_top_n"]):
        return GateDecision(
            True,
            f"always_pass_top_{gc['always_pass_top_n']}",
            rank=rank,
            candidate_score=cs_f,
            signals=disp,
            boosted=boosted,
            research_tier="DEEP_RESEARCH" if tier == "NO_RESEARCH" else tier,
            data_quality=dq,
        )

    score_floor = float(gc["boost_score_floor"]) if boosted else float(gc["min_candidate_score"])
    if cs is None:
        return GateDecision(
            False,
            "MISSING_CANDIDATE_SCORE",
            rank=rank,
            candidate_score=0.0,
            signals=disp,
            boosted=boosted,
            research_tier=tier,
            reject_codes=["MISSING_CANDIDATE_SCORE"],
            data_quality=dq,
        )
    if cs_f < score_floor:
        return GateDecision(
            False,
            "LOW_CANDIDATE_SCORE",
            rank=rank,
            candidate_score=cs_f,
            signals=disp,
            boosted=boosted,
            research_tier=tier,
            reject_codes=["LOW_CANDIDATE_SCORE"],
            data_quality=dq,
        )

    strong, hard_codes = _strong_signal_pass(bundle, gc)
    if hard_codes and not strong:
        return GateDecision(
            False,
            hard_codes[0],
            rank=rank,
            candidate_score=cs_f,
            signals=disp,
            boosted=boosted,
            research_tier=tier,
            reject_codes=hard_codes,
            data_quality=dq,
        )

    if tier == "NO_RESEARCH" and not strong:
        return GateDecision(
            False,
            "NO_RESEARCH_TIER",
            rank=rank,
            candidate_score=cs_f,
            signals=disp,
            boosted=boosted,
            research_tier=tier,
            reject_codes=["NO_RESEARCH_TIER", "WEAK_SIGNALS"],
            data_quality=dq,
        )

    if strong:
        return GateDecision(
            True,
            "SIGNAL_PASS",
            rank=rank,
            candidate_score=cs_f,
            signals=disp,
            boosted=boosted,
            research_tier=tier if tier != "NO_RESEARCH" else "LIGHT_RESEARCH",
            data_quality=dq,
        )

    return GateDecision(
        False,
        "WEAK_SIGNALS",
        rank=rank,
        candidate_score=cs_f,
        signals=disp,
        boosted=boosted,
        research_tier=tier,
        reject_codes=["WEAK_SIGNALS"],
        data_quality=dq,
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
        code_c: dict[str, int] = {}
        for d in self.decisions.values():
            if d.passed:
                continue
            for c in d.reject_codes or [d.reason]:
                code_c[c] = code_c.get(c, 0) + 1
        return {
            "n_in": len(self.passed) + len(self.rejected),
            "n_passed": len(self.passed),
            "n_rejected": len(self.rejected),
            "research_tiers": tiers,
            "reject_reasons": {
                r: sum(1 for d in self.decisions.values() if d.reason == r and not d.passed) for r in reasons
            },
            "reject_codes": code_c,
        }


def apply_research_gate(
    candidates: list[dict[str, Any]],
    cfg: dict[str, Any] | None = None,
) -> GateBatchResult:
    """Sort by candidate_score desc, evaluate gate tiers, annotate rows."""
    gc = _gate_cfg(cfg)
    ranked = sorted(
        candidates,
        key=lambda x: float(x.get("candidate_score") or 0),
        reverse=True,
    )
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
                    reject_codes=["DEEP_BUDGET"],
                    data_quality=dec.data_quality,
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
                    reject_codes=["LIGHT_BUDGET"],
                    data_quality=dec.data_quality,
                )
            elif dec.passed:
                if dec.research_tier == "DEEP_RESEARCH":
                    deep_n += 1
                elif dec.research_tier == "LIGHT_RESEARCH":
                    light_n += 1
        decisions[sym] = dec
        annotated = {
            **row,
            "gate": dec.to_dict(),
            "in_council": dec.passed,
            "research_tier": dec.research_tier,
            "data_quality": dec.data_quality,
        }
        if dec.passed:
            passed.append(annotated)
        else:
            annotated["reject_reason"] = dec.reason
            annotated["reject_codes"] = list(dec.reject_codes or [dec.reason])
            rejected.append(annotated)

    return GateBatchResult(passed=passed, rejected=rejected, decisions=decisions)
