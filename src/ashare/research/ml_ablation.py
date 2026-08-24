"""V5.4 ML Ablation — With vs Without ML ranking on same outcomes (0 retrain)."""

from __future__ import annotations

from typing import Any

from ashare.research.ai_ablation import _mean_stats, _selection_alpha
from ashare.research.signal_attribution import minimum_sample_size


def _ml_score(r: dict[str, Any]) -> float:
    return float(r.get("ml_prediction") or r.get("ml_rank_score") or 0)


def _no_ml_score(r: dict[str, Any]) -> float:
    q = r.get("quant") or {}
    return float(q.get("leader_score") or q.get("factor_score") or r.get("candidate_score") or 0)


def run_ml_ablation(
    reports: list[dict[str, Any]],
    outcomes: list[dict[str, Any]],
    cfg: dict[str, Any] | None = None,
    *,
    top_k: int = 5,
) -> dict[str, Any]:
    """Top-K without ML vs with ML prediction — replay only."""
    from ashare.config_loaders import load_yaml_config

    acfg = dict(load_yaml_config(cfg, "research").get("attribution") or {})
    horizons = list(acfg.get("horizons_days") or [1, 5, 10, 20])
    min_n = minimum_sample_size(cfg)
    outcome_by_sym = {str(o.get("symbol")): o for o in outcomes}
    eligible = []
    for r in reports:
        sym = str(r.get("symbol") or "")
        if _selection_alpha(sym, outcome_by_sym, str(horizons[0])) is None:
            continue
        eligible.append(r)
    if len(eligible) < 2:
        return {"available": False, "insufficient_sample": True, "sample_count": len(eligible)}

    kk = min(top_k, len(eligible))
    a_top = sorted(eligible, key=_no_ml_score, reverse=True)[:kk]
    b_top = sorted(eligible, key=_ml_score, reverse=True)[:kk]
    by_h: dict[str, Any] = {}
    for h in horizons:
        h_key = str(h)
        a_vals = [_selection_alpha(str(r["symbol"]), outcome_by_sym, h_key) for r in a_top]
        b_vals = [_selection_alpha(str(r["symbol"]), outcome_by_sym, h_key) for r in b_top]
        a_vals = [x for x in a_vals if x is not None]
        b_vals = [x for x in b_vals if x is not None]
        a_s, b_s = _mean_stats(a_vals), _mean_stats(b_vals)
        incr = None
        if a_s.get("mean") is not None and b_s.get("mean") is not None:
            incr = float(b_s["mean"]) - float(a_s["mean"])
        n = min(a_s.get("sample_count") or 0, b_s.get("sample_count") or 0)
        status = "INSUFFICIENT_SAMPLE"
        if n >= min_n and incr is not None:
            status = "NEGATIVE_INCREMENTAL_ALPHA" if incr < 0 else ("STRONG" if incr >= 0.01 else "VALID")
        by_h[h_key] = {
            "without_ml": a_s,
            "with_ml": b_s,
            "ml_incremental_alpha": incr,
            "sample_count": n,
            "insufficient_sample": n < min_n,
            "status": status,
        }

    h5 = by_h.get("5") or {}
    return {
        "available": True,
        "method": "ml_ablation_topk",
        "top_k": kk,
        "horizons": by_h,
        "ml_incremental_alpha_t5": h5.get("ml_incremental_alpha"),
        "status": h5.get("status"),
        "note": "0 retrain — ranks replay from persisted ml_prediction",
    }
