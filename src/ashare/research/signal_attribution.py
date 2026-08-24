"""V5.4 Signal Attribution — discovery source alpha from primary_horizons."""

from __future__ import annotations

from typing import Any, Callable

import pandas as pd

from ashare.config_loaders import load_yaml_config


def attribution_cfg(cfg: dict[str, Any] | None) -> dict[str, Any]:
    return dict(load_yaml_config(cfg, "research").get("attribution") or {})


def minimum_sample_size(cfg: dict[str, Any] | None) -> int:
    acfg = attribution_cfg(cfg)
    return int(acfg.get("minimum_sample_size") or acfg.get("minimum_sample") or 30)


def resolve_primary_source(
    sources: list[str] | None,
    priority: list[str] | None = None,
) -> dict[str, Any]:
    """Pick one primary discovery source; rest are secondary."""
    srcs = sorted({str(s).lower() for s in (sources or []) if s})
    prio = [str(p).lower() for p in (priority or ["profit", "event", "quant", "news", "ml"])]
    primary = "unknown"
    for p in prio:
        if p in srcs:
            primary = p
            break
    if primary == "unknown" and srcs:
        primary = srcs[0]
    secondary = [s for s in srcs if s != primary]
    return {"primary_source": primary, "secondary_sources": secondary, "candidate_sources": srcs}


def discovery_primary(outcome: dict[str, Any]) -> str:
    return str(
        outcome.get("discovery_primary_source")
        or outcome.get("primary_source")
        or "unknown"
    )


def horizon_metrics(outcome: dict[str, Any], horizon: str | int) -> dict[str, Any] | None:
    """Read metrics from primary_horizons only (V5.4 truth rule)."""
    cell = (outcome.get("primary_horizons") or {}).get(str(horizon)) or {}
    if cell.get("status") == "pending":
        return None
    ret = cell.get("actual_return")
    if ret is None:
        ret = cell.get("total_return")
    if ret is None and cell.get("realized_return") is not None:
        ret = cell.get("realized_return")
    if ret is None:
        return None
    return {
        "realized_return": float(ret),
        "benchmark_return": cell.get("benchmark_return") or cell.get("market_benchmark_return"),
        "market_alpha": cell.get("market_alpha"),
        "selection_alpha": cell.get("selection_alpha"),
    }


def _stats_pack(values: list[float]) -> dict[str, Any]:
    if not values:
        return {}
    s = pd.Series(values)
    return {
        "mean": float(s.mean()),
        "median": float(s.median()),
        "win_rate": float((s > 0).mean()),
        "std": float(s.std()) if len(s) > 1 else 0.0,
        "sample_count": len(values),
    }


def source_status_label(
    mean_alpha: float | None,
    *,
    sample_count: int,
    minimum_sample: int,
    incremental: float | None = None,
) -> str:
    if sample_count < minimum_sample or mean_alpha is None:
        return "INSUFFICIENT_SAMPLE"
    if incremental is not None and incremental < 0:
        return "NEGATIVE_INCREMENTAL_ALPHA"
    if mean_alpha < 0:
        return "NEGATIVE"
    if incremental is not None and incremental <= 0:
        return "INEFFICIENT"
    if mean_alpha >= 0.02:
        return "STRONG"
    if mean_alpha >= 0.005:
        return "VALID"
    return "WEAK"


def _aggregate_horizons(
    outcomes: list[dict[str, Any]],
    *,
    filter_fn: Callable[[dict[str, Any]], bool],
    horizons: list[int],
    minimum_sample: int,
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for h in horizons:
        h_key = str(h)
        rets, mkt, sel = [], [], []
        for o in outcomes:
            if not filter_fn(o):
                continue
            m = horizon_metrics(o, h)
            if not m:
                continue
            rets.append(float(m["realized_return"]))
            if m.get("market_alpha") is not None:
                mkt.append(float(m["market_alpha"]))
            if m.get("selection_alpha") is not None:
                sel.append(float(m["selection_alpha"]))
        n = len(rets)
        if n < minimum_sample:
            out[h_key] = {
                "insufficient_sample": True,
                "sample_count": n,
                "minimum_sample": minimum_sample,
                "status": "INSUFFICIENT_SAMPLE",
            }
        else:
            sel_stats = _stats_pack(sel) if sel else _stats_pack(mkt) if mkt else _stats_pack(rets)
            out[h_key] = {
                "insufficient_sample": False,
                "sample_count": n,
                "status": source_status_label(
                    sel_stats.get("mean") if sel_stats else None,
                    sample_count=n,
                    minimum_sample=minimum_sample,
                ),
                "realized_return": _stats_pack(rets),
                "market_alpha": _stats_pack(mkt) if mkt else None,
                "selection_alpha": _stats_pack(sel) if sel else None,
            }
    return out


def enrich_outcome_sources(outcome: dict[str, Any], cfg: dict[str, Any] | None) -> dict[str, Any]:
    """Attach discovery_primary_source / secondary_sources (never overwrites entry source)."""
    acfg = attribution_cfg(cfg)
    resolved = resolve_primary_source(
        outcome.get("candidate_sources") or outcome.get("discovery_sources"),
        acfg.get("primary_source_priority"),
    )
    outcome["discovery_primary_source"] = resolved["primary_source"]
    outcome["secondary_sources"] = resolved["secondary_sources"]
    return outcome


def cohort_compare(
    outcomes: list[dict[str, Any]],
    *,
    tag: str,
    cfg: dict[str, Any] | None = None,
    filter_with: Callable[[dict[str, Any]], bool] | None = None,
    filter_without: Callable[[dict[str, Any]], bool] | None = None,
) -> dict[str, Any]:
    """Compare two cohorts; default is tag participation in candidate_sources."""
    acfg = attribution_cfg(cfg)
    horizons = list(acfg.get("horizons_days") or [1, 5, 10, 20])
    minimum_sample = minimum_sample_size(cfg)
    tag_l = tag.lower()

    if filter_with is None:

        def filter_with(o: dict[str, Any]) -> bool:
            return tag_l in {str(s).lower() for s in (o.get("candidate_sources") or [])}

    if filter_without is None:

        def filter_without(o: dict[str, Any]) -> bool:
            return not filter_with(o)

    with_tag = _aggregate_horizons(outcomes, filter_fn=filter_with, horizons=horizons, minimum_sample=minimum_sample)
    without_tag = _aggregate_horizons(
        outcomes, filter_fn=filter_without, horizons=horizons, minimum_sample=minimum_sample
    )
    incremental: dict[str, Any] = {}
    for h in horizons:
        h_key = str(h)
        w = with_tag.get(h_key) or {}
        wo = without_tag.get(h_key) or {}
        if w.get("insufficient_sample") or wo.get("insufficient_sample"):
            incremental[h_key] = {"insufficient_sample": True, "status": "INSUFFICIENT_SAMPLE"}
            continue
        w_sel = (w.get("selection_alpha") or {}).get("mean")
        wo_sel = (wo.get("selection_alpha") or {}).get("mean")
        if w_sel is not None and wo_sel is not None:
            incr = float(w_sel) - float(wo_sel)
            incremental[h_key] = {
                "insufficient_sample": False,
                "incremental_selection_alpha": incr,
                "status": source_status_label(w_sel, sample_count=w.get("sample_count", 0), minimum_sample=minimum_sample, incremental=incr),
            }
        else:
            w_m = (w.get("market_alpha") or {}).get("mean")
            wo_m = (wo.get("market_alpha") or {}).get("mean")
            if w_m is not None and wo_m is not None:
                incr = float(w_m) - float(wo_m)
                incremental[h_key] = {
                    "insufficient_sample": False,
                    "incremental_market_alpha": incr,
                    "status": source_status_label(w_m, sample_count=w.get("sample_count", 0), minimum_sample=minimum_sample, incremental=incr),
                }
            else:
                incremental[h_key] = {"insufficient_sample": True, "note": "no_alpha_metrics", "status": "INSUFFICIENT_SAMPLE"}

    return {
        "tag": tag,
        "with_tag": with_tag,
        "without_tag": without_tag,
        "incremental": incremental,
    }


def news_discovery_cohort(outcomes: list[dict[str, Any]], cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """primary_source == news vs != news (Discovery, not participation)."""

    def _news_primary(o: dict[str, Any]) -> bool:
        return discovery_primary(o) == "news"

    return cohort_compare(
        outcomes,
        tag="news_discovery",
        cfg=cfg,
        filter_with=_news_primary,
        filter_without=lambda o: discovery_primary(o) != "news",
    )


def news_evidence_cohort(outcomes: list[dict[str, Any]], cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """primary != news but secondary contains news vs no news in secondary."""

    def _with(o: dict[str, Any]) -> bool:
        sec = {str(s).lower() for s in (o.get("secondary_sources") or [])}
        return discovery_primary(o) != "news" and "news" in sec

    def _without(o: dict[str, Any]) -> bool:
        sec = {str(s).lower() for s in (o.get("secondary_sources") or [])}
        return discovery_primary(o) != "news" and "news" not in sec

    return cohort_compare(outcomes, tag="news_evidence", cfg=cfg, filter_with=_with, filter_without=_without)


def primary_source_cohort(outcomes: list[dict[str, Any]], source: str, cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    src = source.lower()

    def _with(o: dict[str, Any]) -> bool:
        return discovery_primary(o) == src

    return cohort_compare(
        outcomes,
        tag=src,
        cfg=cfg,
        filter_with=_with,
        filter_without=lambda o: discovery_primary(o) != src,
    )


def summarize_signal_attribution(
    outcomes: list[dict[str, Any]],
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Discovery attribution by primary source + participation tags + news splits."""
    acfg = attribution_cfg(cfg)
    horizons = list(acfg.get("horizons_days") or [1, 5, 10, 20])
    minimum_sample = minimum_sample_size(cfg)
    tags = ("quant", "news", "event", "profit", "ml")

    by_tag: dict[str, Any] = {}
    for tag in tags:
        by_tag[tag] = _aggregate_horizons(
            outcomes,
            filter_fn=lambda o, t=tag: t in {str(s).lower() for s in (o.get("candidate_sources") or [])},
            horizons=horizons,
            minimum_sample=minimum_sample,
        )

    by_primary: dict[str, Any] = {}
    primaries = {discovery_primary(o) for o in outcomes}
    for p in sorted(primaries):
        by_primary[p] = _aggregate_horizons(
            outcomes,
            filter_fn=lambda o, pr=p: discovery_primary(o) == pr,
            horizons=horizons,
            minimum_sample=minimum_sample,
        )

    profit_data_unavailable = all(
        not (o.get("profit_inflection") or {}).get("available", True)
        for o in outcomes
        if discovery_primary(o) == "profit"
    ) if outcomes else False

    return {
        "available": bool(outcomes),
        "horizons": horizons,
        "minimum_sample": minimum_sample,
        "by_tag": by_tag,
        "by_primary_source": by_primary,
        "cohorts": {
            "news_discovery": news_discovery_cohort(outcomes, cfg),
            "news_evidence": news_evidence_cohort(outcomes, cfg),
            "event_primary": primary_source_cohort(outcomes, "event", cfg),
            "profit_primary": primary_source_cohort(outcomes, "profit", cfg),
            "quant_primary": primary_source_cohort(outcomes, "quant", cfg),
        },
        "profit_data_unavailable": profit_data_unavailable,
        "note": "by_tag = research participation; by_primary_source / cohorts = discovery",
    }
