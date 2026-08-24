from __future__ import annotations

from typing import Any, Callable

import pandas as pd

from ashare.research.signal_attribution import horizon_metrics, minimum_sample_size, source_status_label

_BUCKETS = [(0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.01)]


def _field_value(outcome: dict[str, Any], field: str) -> float | None:
    if field == "news_intelligence_score":
        v = outcome.get("news_intelligence_score")
        if v is None:
            intel = outcome.get("news_intelligence") or {}
            v = intel.get("news_intelligence_score")
    elif field in {"importance", "novelty"}:
        intel = outcome.get("news_intelligence") or {}
        v = intel.get(field)
    else:
        v = outcome.get(field)
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def calibrate_buckets(
    outcomes: list[dict[str, Any]],
    field: str,
    *,
    horizons: list[int] | None = None,
    min_n: int = 5,
) -> dict[str, Any]:
    horizons = horizons or [5, 10, 20]
    buckets_out: list[dict[str, Any]] = []
    means: list[float] = []

    for lo, hi in _BUCKETS:
        rets_by_h: dict[str, list[float]] = {str(h): [] for h in horizons}
        for o in outcomes:
            val = _field_value(o, field)
            if val is None or val < lo or val >= hi:
                continue
            for h in horizons:
                m = horizon_metrics(o, h)
                if not m:
                    continue
                ex = m.get("selection_alpha")
                if ex is None:
                    ex = m.get("market_alpha")
                if ex is not None:
                    rets_by_h[str(h)].append(float(ex))

        hz_stats: dict[str, Any] = {}
        for h in horizons:
            vals = rets_by_h[str(h)]
            n = len(vals)
            if n < min_n:
                hz_stats[str(h)] = {"status": "INSUFFICIENT_SAMPLE", "sample_count": n}
            else:
                mean = float(pd.Series(vals).mean())
                hz_stats[str(h)] = {
                    "status": source_status_label(mean, sample_count=n, minimum_sample=min_n),
                    "sample_count": n,
                    "excess_return_mean": mean,
                }
                if h == 5:
                    means.append(mean)

        buckets_out.append({"range": f"{lo:.1f}-{hi:.1f}", "horizons": hz_stats})

    monotonic = False
    if len(means) >= 3:
        monotonic = all(means[i] <= means[i + 1] for i in range(len(means) - 1))

    return {
        "field": field,
        "buckets": buckets_out,
        "monotonic_t5": monotonic,
        "minimum_sample": min_n,
    }


def news_quant_quadrants(
    outcomes: list[dict[str, Any]],
    *,
    news_threshold: float = 0.12,
    quant_threshold: float = 0.15,
    horizons: list[int] | None = None,
    min_n: int = 5,
) -> dict[str, Any]:
    horizons = horizons or [5, 10, 20]
    quads: dict[str, list[dict[str, Any]]] = {
        "news_strong_quant_strong": [],
        "news_strong_quant_weak": [],
        "news_weak_quant_strong": [],
        "news_weak_quant_weak": [],
    }
    for o in outcomes:
        try:
            ns = float(o.get("news_score") or 0)
            qs = float(o.get("leader_score") or o.get("candidate_score") or 0)
        except (TypeError, ValueError):
            continue
        nk = "strong" if ns >= news_threshold else "weak"
        qk = "strong" if qs >= quant_threshold else "weak"
        key = f"news_{nk}_quant_{qk}"
        quads[key].append(o)

    out: dict[str, Any] = {}
    for name, rows in quads.items():
        hz: dict[str, Any] = {}
        for h in horizons:
            vals = []
            for o in rows:
                m = horizon_metrics(o, h)
                if not m:
                    continue
                ex = m.get("selection_alpha") or m.get("market_alpha")
                if ex is not None:
                    vals.append(float(ex))
            n = len(vals)
            if n < min_n:
                hz[str(h)] = {"status": "INSUFFICIENT_SAMPLE", "sample_count": n}
            else:
                mean = float(pd.Series(vals).mean())
                hz[str(h)] = {
                    "status": source_status_label(mean, sample_count=n, minimum_sample=min_n),
                    "sample_count": n,
                    "excess_return_mean": mean,
                }
        out[name] = hz
    return out


def build_news_calibration(
    outcomes: list[dict[str, Any]],
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from ashare.config_loaders import load_yaml_config

    acfg = dict(load_yaml_config(cfg, "research").get("attribution") or {})
    cal = dict(load_yaml_config(cfg, "research").get("news_calibration") or {})
    min_n = int(cal.get("minimum_sample") or acfg.get("minimum_sample") or 5)
    horizons = list(acfg.get("horizons_days") or [5, 10, 20])
    news_thr = float(cal.get("news_score_threshold") or 0.12)
    quant_thr = float(cal.get("quant_score_threshold") or 0.15)

    return {
        "score": calibrate_buckets(outcomes, "news_intelligence_score", horizons=horizons, min_n=min_n),
        "importance": calibrate_buckets(outcomes, "importance", horizons=horizons, min_n=min_n),
        "novelty": calibrate_buckets(outcomes, "novelty", horizons=horizons, min_n=min_n),
        "quadrants": news_quant_quadrants(
            outcomes,
            news_threshold=news_thr,
            quant_threshold=quant_thr,
            horizons=horizons,
            min_n=min_n,
        ),
    }
