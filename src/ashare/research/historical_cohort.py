from __future__ import annotations

from typing import Any

import pandas as pd

from ashare.research.signal_attribution import horizon_metrics, minimum_sample_size, source_status_label


def _bucket(v: float | None, edges: list[float]) -> str:
    if v is None:
        return "unknown"
    for i, (lo, hi) in enumerate(zip(edges, edges[1:])):
        if lo <= v < hi:
            return f"{lo:.1f}-{hi:.1f}"
    return f">={edges[-1]:.1f}"


_SCORE_EDGES = [0.0, 0.2, 0.4, 0.6, 0.8, 1.01]
_QUANT_EDGES = [0.0, 0.12, 0.25, 0.4, 0.6, 1.01]


def cohort_key(candidate: dict[str, Any]) -> dict[str, str]:
    intel = candidate.get("news_intelligence") or (candidate.get("news_discovery") or {}).get("news_intelligence") or {}
    et = str(
        intel.get("event_type")
        or intel.get("normalized_event_type")
        or (candidate.get("news_discovery") or {}).get("event_type")
        or "unknown"
    )
    ns = float(candidate.get("news_score") or intel.get("news_intelligence_score") or 0)
    imp = float(intel.get("importance") or 0)
    nov = float(intel.get("novelty") or 0)
    qs = float(candidate.get("leader_score") or candidate.get("candidate_score") or 0)
    return {
        "event_type": et,
        "news_score_bucket": _bucket(ns, _SCORE_EDGES),
        "importance_bucket": _bucket(imp, _SCORE_EDGES),
        "novelty_bucket": _bucket(nov, _SCORE_EDGES),
        "quant_bucket": _bucket(qs, _QUANT_EDGES),
    }


def match_cohort(outcome: dict[str, Any], key: dict[str, str]) -> bool:
    intel = outcome.get("news_intelligence") or {}
    okey = {
        "event_type": str(intel.get("event_type") or outcome.get("event_type") or "unknown"),
        "news_score_bucket": _bucket(float(outcome.get("news_intelligence_score") or 0), _SCORE_EDGES),
        "importance_bucket": _bucket(float(intel.get("importance") or 0), _SCORE_EDGES),
        "novelty_bucket": _bucket(float(intel.get("novelty") or 0), _SCORE_EDGES),
        "quant_bucket": _bucket(float(outcome.get("leader_score") or outcome.get("candidate_score") or 0), _QUANT_EDGES),
    }
    matches = sum(1 for k in ("event_type", "news_score_bucket", "importance_bucket") if okey.get(k) == key.get(k))
    return matches >= 2


def build_historical_cohort(
    candidate: dict[str, Any],
    outcomes: list[dict[str, Any]],
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Structured historical cohort — not AI similarity."""
    key = cohort_key(candidate)
    min_n = minimum_sample_size(cfg)
    matched = [o for o in outcomes if match_cohort(o, key)]
    horizons = [1, 5, 10, 20]
    hz_out: dict[str, Any] = {}
    for h in horizons:
        rets, excess = [], []
        for o in matched:
            m = horizon_metrics(o, h)
            if not m:
                continue
            rets.append(float(m["realized_return"]))
            ex = m.get("selection_alpha")
            if ex is None:
                ex = m.get("market_alpha")
            if ex is not None:
                excess.append(float(ex))
        n = len(rets)
        if n < min_n:
            hz_out[str(h)] = {"status": "INSUFFICIENT_SAMPLE", "sample_count": n, "minimum_sample": min_n}
        else:
            exs = excess or rets
            s = pd.Series(exs)
            hz_out[str(h)] = {
                "status": source_status_label(float(s.mean()), sample_count=n, minimum_sample=min_n),
                "sample_count": n,
                "excess_return_mean": float(s.mean()),
                "hit_rate": float((s > 0).mean()),
                "max_drawdown": float((s.cumsum() - s.cumsum().cummax()).min()) if len(s) > 1 else 0.0,
            }
    return {
        "label": "历史同类信号",
        "note": "按事件类型 + 分数/重要性分桶结构化匹配，非 AI 相似度。",
        "cohort_key": key,
        "sample_count": len(matched),
        "horizons": hz_out,
    }
