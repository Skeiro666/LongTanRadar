"""V5.4 AI Council Ablation — No Council vs With Council, 0 extra LLM."""

from __future__ import annotations

from typing import Any

import pandas as pd

from ashare.config_loaders import load_yaml_config
from ashare.research.signal_attribution import horizon_metrics


def _attribution_cfg(cfg: dict[str, Any] | None) -> dict[str, Any]:
    from ashare.research.signal_attribution import minimum_sample_size

    acfg = dict(load_yaml_config(cfg, "research").get("attribution") or {})
    acfg["_min_sample"] = minimum_sample_size(cfg)
    return acfg


def _no_council_score(r: dict[str, Any]) -> float:
    q = r.get("quant") or {}
    return float(q.get("factor_score") or q.get("leader_score") or r.get("candidate_score") or 0)


def _with_council_score(r: dict[str, Any]) -> float:
    rating = str(
        (r.get("decision") or {}).get("research_rating")
        or (r.get("chairman") or {}).get("rating")
        or "WATCH"
    )
    weights = {"STRONG_BUY": 3.0, "BUY": 2.0, "WATCH": 1.0, "PASS": 0.0, "SELL": -1.0}
    conf = float((r.get("chairman") or {}).get("confidence") or 0)
    return weights.get(rating, 0.5) + conf


def _selection_alpha(sym: str, outcome_by_sym: dict[str, dict], horizon: str) -> float | None:
    m = horizon_metrics(outcome_by_sym.get(sym) or {}, horizon)
    if not m:
        return None
    if m.get("selection_alpha") is not None:
        return float(m["selection_alpha"])
    if m.get("market_alpha") is not None:
        return float(m["market_alpha"])
    return float(m["realized_return"])


def _mean_stats(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"sample_count": 0, "mean": None, "median": None, "win_rate": None, "std": None}
    s = pd.Series(values)
    return {
        "sample_count": len(values),
        "mean": float(s.mean()),
        "median": float(s.median()),
        "win_rate": float((s > 0).mean()),
        "std": float(s.std()) if len(s) > 1 else 0.0,
    }


def _efficiency_status(incremental: float | None, llm_cost: float, n: int, min_sample: int) -> str:
    if n < min_sample or incremental is None:
        return "UNPROVEN"
    if incremental < 0:
        return "NEGATIVE_INCREMENTAL_ALPHA"
    if llm_cost <= 0:
        return "UNPROVEN"
    eff = incremental / llm_cost
    if eff >= 0.5:
        return "STRONG"
    if eff >= 0.1:
        return "WEAK"
    return "INEFFICIENT"


def run_council_ablation(
    reports: list[dict[str, Any]],
    outcomes: list[dict[str, Any]],
    cfg: dict[str, Any] | None = None,
    *,
    top_k: int | None = None,
    llm_cost_usd: float | None = None,
) -> dict[str, Any]:
    """
    Experiment A: rank by quant score (No Council).
    Experiment B: rank by chairman rating (With Council).
    Same universe, primary_horizons only.
    """
    acfg = _attribution_cfg(cfg)
    horizons = list(acfg.get("horizons_days") or [1, 5, 10, 20])
    minimum_sample = int(acfg.get("_min_sample") or 30)
    k = int(top_k or (load_yaml_config(cfg, "research").get("role_ablation") or {}).get("top_k") or 5)

    outcome_by_sym = {str(o.get("symbol")): o for o in outcomes}
    eligible: list[dict[str, Any]] = []
    for r in reports:
        rating = str(
            (r.get("decision") or {}).get("research_rating") or (r.get("chairman") or {}).get("rating") or ""
        )
        if rating in {"GATE_SKIP", "SKIP"}:
            continue
        sym = str(r.get("symbol") or "")
        if _selection_alpha(sym, outcome_by_sym, str(horizons[0])) is None:
            continue
        eligible.append(r)

    if len(eligible) < 2:
        return {
            "available": False,
            "insufficient_sample": True,
            "sample_count": len(eligible),
            "cost_unavailable": float(llm_cost_usd or 0) <= 0,
            "note": "need >=2 symbols with primary horizon returns",
        }

    kk = min(k, len(eligible))
    a_top = sorted(eligible, key=_no_council_score, reverse=True)[:kk]
    b_top = sorted(eligible, key=_with_council_score, reverse=True)[:kk]

    by_horizon: dict[str, Any] = {}
    for h in horizons:
        h_key = str(h)
        a_vals = [_selection_alpha(str(r["symbol"]), outcome_by_sym, h_key) for r in a_top]
        b_vals = [_selection_alpha(str(r["symbol"]), outcome_by_sym, h_key) for r in b_top]
        a_vals = [x for x in a_vals if x is not None]
        b_vals = [x for x in b_vals if x is not None]
        a_stats = _mean_stats(a_vals)
        b_stats = _mean_stats(b_vals)
        incr = None
        if a_stats.get("mean") is not None and b_stats.get("mean") is not None:
            incr = float(b_stats["mean"]) - float(a_stats["mean"])
        n = min(a_stats.get("sample_count") or 0, b_stats.get("sample_count") or 0)
        st = "INSUFFICIENT_SAMPLE" if n < minimum_sample else (
            "NEGATIVE_INCREMENTAL_ALPHA" if incr is not None and incr < 0 else "OK"
        )
        by_horizon[h_key] = {
            "no_council": a_stats,
            "with_council": b_stats,
            "ai_incremental_alpha": incr,
            "insufficient_sample": n < minimum_sample,
            "sample_count": n,
            "status": st,
        }

    cost = float(llm_cost_usd or 0)
    h5 = by_horizon.get("5") or {}
    incr5 = h5.get("ai_incremental_alpha")
    n5 = h5.get("sample_count") or 0
    ai_efficiency = None
    cost_unavailable = cost <= 0
    if not cost_unavailable and incr5 is not None:
        ai_efficiency = float(incr5) / cost

    return {
        "available": True,
        "method": "council_ablation_topk",
        "experiment_a": "no_council_quant_score",
        "experiment_b": "with_council_chairman_rating",
        "top_k": kk,
        "universe_size": len(eligible),
        "horizons": by_horizon,
        "llm_cost_usd": cost if cost > 0 else None,
        "ai_efficiency": ai_efficiency,
        "cost_unavailable": cost_unavailable,
        "status": _efficiency_status(incr5, cost, n5, minimum_sample),
        "note": "Replay from persisted reports — 0 additional LLM calls",
    }
