from __future__ import annotations

from typing import Any, Callable

import pandas as pd

from ashare.config_loaders import load_yaml_config
from ashare.research.signal_attribution import (
    discovery_primary,
    horizon_metrics,
    minimum_sample_size,
    source_status_label,
)


def _stats(values: list[float]) -> dict[str, Any]:
    if not values:
        return {}
    s = pd.Series(values)
    cum = s.cumsum()
    dd = float((cum - cum.cummax()).min()) if len(s) > 1 else 0.0
    return {
        "mean": float(s.mean()),
        "median": float(s.median()),
        "win_rate": float((s > 0).mean()),
        "max_drawdown": dd,
        "sample_count": len(values),
    }


def _horizon_block(
    outcomes: list[dict[str, Any]],
    *,
    filter_fn: Callable[[dict[str, Any]], bool],
    horizon: int,
    min_n: int,
) -> dict[str, Any]:
    rets, bench, excess = [], [], []
    for o in outcomes:
        if not filter_fn(o):
            continue
        m = horizon_metrics(o, horizon)
        if not m:
            continue
        rets.append(float(m["realized_return"]))
        if m.get("benchmark_return") is not None:
            bench.append(float(m["benchmark_return"]))
        if m.get("selection_alpha") is not None:
            excess.append(float(m["selection_alpha"]))
        elif m.get("market_alpha") is not None:
            excess.append(float(m["market_alpha"]))
    n = len(rets)
    if n < min_n:
        return {"status": "INSUFFICIENT_SAMPLE", "sample_count": n, "minimum_sample": min_n}
    return {
        "status": source_status_label(
            (excess and float(pd.Series(excess).mean())) or None,
            sample_count=n,
            minimum_sample=min_n,
        ),
        "sample_count": n,
        "return": _stats(rets),
        "benchmark_return": _stats(bench) if bench else None,
        "excess_return": _stats(excess) if excess else _stats(rets),
        "hit_rate": _stats(excess or rets).get("win_rate"),
    }


def _aggregate(
    outcomes: list[dict[str, Any]],
    *,
    filter_fn: Callable[[dict[str, Any]], bool],
    cfg: dict[str, Any] | None,
) -> dict[str, Any]:
    acfg = dict(load_yaml_config(cfg, "research").get("attribution") or {})
    horizons = list(acfg.get("horizons_days") or [1, 5, 10, 20])
    min_n = minimum_sample_size(cfg)
    out: dict[str, Any] = {}
    for h in horizons:
        out[str(h)] = _horizon_block(outcomes, filter_fn=filter_fn, horizon=h, min_n=min_n)
    return out


def _has_news(o: dict[str, Any]) -> bool:
    srcs = {str(s).lower() for s in (o.get("candidate_sources") or [])}
    return "news" in srcs


def _has_factor(o: dict[str, Any]) -> bool:
    srcs = {str(s).lower() for s in (o.get("candidate_sources") or [])}
    return bool(srcs & {"quant", "event", "profit", "ml"})


def _council_used(o: dict[str, Any]) -> bool:
    routing = o.get("ai_routing") or {}
    return str(routing.get("routing_level") or "").upper() not in {"", "LOW", "NONE"}


def news_alpha_bucket(o: dict[str, Any], quant_top_n: set[str] | None = None) -> str:
    """A=Quant+News, B=News Only, C=Quant Only, D=Neither."""
    sym = str(o.get("symbol") or "")
    primary = discovery_primary(o)
    if o.get("quant_top_n_at_signal") is not None:
        in_quant = bool(o.get("quant_top_n_at_signal"))
    else:
        in_quant = sym in (quant_top_n or set())
    has_news = primary == "news" or _has_news(o)
    if has_news and in_quant:
        return "A"
    if has_news and not in_quant:
        return "B"
    if not has_news and in_quant:
        return "C"
    return "D"


def build_news_alpha_attribution(
    outcomes: list[dict[str, Any]],
    cfg: dict[str, Any] | None = None,
    *,
    quant_top_n: set[str] | None = None,
) -> dict[str, Any]:
    min_n = minimum_sample_size(cfg)

    def disc(o: dict[str, Any]) -> bool:
        return discovery_primary(o) == "news"

    def evidence(o: dict[str, Any]) -> bool:
        sec = {str(s).lower() for s in (o.get("secondary_sources") or [])}
        return "news" in sec and discovery_primary(o) != "news"

    def nf(o: dict[str, Any]) -> bool:
        return _has_news(o) and _has_factor(o)

    def nc(o: dict[str, Any]) -> bool:
        return _has_news(o) and _has_factor(o) and _council_used(o)

    buckets = {
        "A_quant_plus_news": lambda o: news_alpha_bucket(o, quant_top_n) == "A",
        "B_news_only": lambda o: news_alpha_bucket(o, quant_top_n) == "B",
        "C_quant_only": lambda o: news_alpha_bucket(o, quant_top_n) == "C",
        "D_neither": lambda o: news_alpha_bucket(o, quant_top_n) == "D",
    }
    return {
        "available": bool(outcomes),
        "minimum_sample_size": min_n,
        "news_discovery_alpha": _aggregate(outcomes, filter_fn=disc, cfg=cfg),
        "news_evidence_alpha": _aggregate(outcomes, filter_fn=evidence, cfg=cfg),
        "news_factor_alpha": _aggregate(outcomes, filter_fn=nf, cfg=cfg),
        "news_council_alpha": _aggregate(outcomes, filter_fn=nc, cfg=cfg),
        "ab_buckets": {k: _aggregate(outcomes, filter_fn=fn, cfg=cfg) for k, fn in buckets.items()},
    }
