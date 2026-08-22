"""V5.2 Phase 4 — Role ablation (experimental, offline replay)."""

from __future__ import annotations

from typing import Any

import pandas as pd

from ashare.research.dynamic_council import COUNCIL_ROLE_IDS

_ROLE_WEIGHTS: dict[str, float] = {
    "fundamental": 1.0,
    "quant": 1.0,
    "event": 1.0,
    "valuation": 0.8,
    "bear": 0.6,
}


def _role_opinions(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    council = report.get("council") or {}
    return {k: v for k, v in council.items() if not str(k).startswith("_") and isinstance(v, dict)}


def synthetic_chair_score(opinions: dict[str, dict[str, Any]], *, exclude_role: str | None = None) -> float:
    """Replay chairman-style aggregate from role scores — no LLM."""
    pos = 0.0
    pos_w = 0.0
    bear = float((opinions.get("bear") or {}).get("score") or 0) if exclude_role != "bear" else 0.0
    for rid, op in opinions.items():
        if rid == exclude_role:
            continue
        if rid == "bear":
            continue
        if op.get("status") in {"skipped", "failed", "unavailable"}:
            continue
        w = _ROLE_WEIGHTS.get(rid, 1.0)
        pos += float(op.get("score") or 0) * w
        pos_w += w
    avg = pos / pos_w if pos_w else 0.0
    return avg + bear * 0.35


def _horizon_return(outcome: dict[str, Any], horizon: str) -> float | None:
    cell = (outcome.get("horizons") or {}).get(str(horizon)) or {}
    for key in ("selection_alpha", "market_alpha", "excess_return", "actual_return"):
        if cell.get(key) is not None:
            return float(cell[key])
    return None


def compute_role_ablation(
    reports: list[dict[str, Any]],
    outcomes: list[dict[str, Any]],
    *,
    horizon: str = "5",
    top_k: int = 5,
) -> dict[str, Any]:
    """
    Experimental: drop one council role at a time and replay synthetic ranking vs full council.
    Descriptive only — not causal proof of role value.
    """
    outcome_by_sym = {str(o.get("symbol")): o for o in outcomes}
    eligible: list[dict[str, Any]] = []
    for r in reports:
        rating = str((r.get("decision") or {}).get("research_rating") or (r.get("chairman") or {}).get("rating") or "")
        if rating in {"GATE_SKIP", "SKIP"}:
            continue
        sym = str(r.get("symbol") or "")
        if _horizon_return(outcome_by_sym.get(sym) or {}, horizon) is None:
            continue
        if not _role_opinions(r):
            continue
        eligible.append(r)

    if len(eligible) < 2:
        return {
            "available": False,
            "insufficient_sample": True,
            "sample_count": len(eligible),
            "note": "need >=2 reports with council opinions and realized returns",
        }

    k = min(top_k, len(eligible))

    def _mean_top(reps: list[dict[str, Any]], score_fn) -> dict[str, Any]:
        ranked = sorted(eligible, key=lambda r: score_fn(r), reverse=True)[:k]
        rets = [_horizon_return(outcome_by_sym[str(r["symbol"])], horizon) for r in ranked]
        rets = [x for x in rets if x is not None]
        if not rets:
            return {"n": 0, "mean_return": None, "symbols": []}
        s = pd.Series(rets)
        return {
            "n": len(rets),
            "mean_return": float(s.mean()),
            "symbols": [r.get("symbol") for r in ranked],
        }

    def full_score(r: dict[str, Any]) -> float:
        rating = str((r.get("chairman") or {}).get("rating") or "WATCH")
        weights = {"STRONG_BUY": 3.0, "BUY": 2.0, "WATCH": 1.0, "PASS": 0.0, "SELL": -1.0, "AVOID": -0.5}
        conf = float((r.get("chairman") or {}).get("confidence") or 0)
        return weights.get(rating, 0.5) + conf

    full = _mean_top(eligible, full_score)
    full_mean = full.get("mean_return")

    by_role: dict[str, Any] = {}
    for rid in COUNCIL_ROLE_IDS:
        if rid == "chair":
            continue

        def score_without(exclude: str):
            def _fn(r: dict[str, Any]) -> float:
                return synthetic_chair_score(_role_opinions(r), exclude_role=exclude)

            return _fn

        ablated = _mean_top(eligible, score_without(rid))
        ab_mean = ablated.get("mean_return")
        delta = None
        if full_mean is not None and ab_mean is not None:
            delta = float(ab_mean) - float(full_mean)
        by_role[rid] = {
            "excluded_role": rid,
            "topk_mean_return": ab_mean,
            "delta_vs_full_council": delta,
            "topk_symbols": ablated.get("symbols") or [],
            "interpretation": "role_drop_hurts" if (delta is not None and delta < -0.001) else "neutral_or_helped",
        }

    return {
        "available": True,
        "experimental": True,
        "method": "offline_role_drop_replay",
        "horizon": str(horizon),
        "top_k": k,
        "sample_count": len(eligible),
        "full_council_topk": full,
        "by_role": by_role,
        "note": "Experimental replay — synthetic scores, not re-run LLM. See ai_incremental_alpha for canonical metric.",
    }
