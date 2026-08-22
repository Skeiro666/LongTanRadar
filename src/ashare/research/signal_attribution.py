"""V5.4 Signal Attribution — primary_source, multi-horizon alpha from primary_horizons."""

from __future__ import annotations

from typing import Any

import pandas as pd

from ashare.config_loaders import load_yaml_config


def attribution_cfg(cfg: dict[str, Any] | None) -> dict[str, Any]:
    return dict(load_yaml_config(cfg, "research").get("attribution") or {})


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


def _aggregate_horizons(
    outcomes: list[dict[str, Any]],
    *,
    filter_fn,
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
            }
        else:
            out[h_key] = {
                "insufficient_sample": False,
                "sample_count": n,
                "realized_return": _stats_pack(rets),
                "market_alpha": _stats_pack(mkt) if mkt else None,
                "selection_alpha": _stats_pack(sel) if sel else None,
            }
    return out


def enrich_outcome_sources(outcome: dict[str, Any], cfg: dict[str, Any] | None) -> dict[str, Any]:
    """Attach primary_source / secondary_sources to one outcome."""
    acfg = attribution_cfg(cfg)
    resolved = resolve_primary_source(
        outcome.get("candidate_sources") or outcome.get("discovery_sources"),
        acfg.get("primary_source_priority"),
    )
    outcome["primary_source"] = resolved["primary_source"]
    outcome["secondary_sources"] = resolved["secondary_sources"]
    return outcome


def summarize_signal_attribution(
    outcomes: list[dict[str, Any]],
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Per tag and primary_source: T+1/5/10/20 alpha from primary_horizons."""
    acfg = attribution_cfg(cfg)
    horizons = list(acfg.get("horizons_days") or [1, 5, 10, 20])
    minimum_sample = int(acfg.get("minimum_sample") or 5)
    tags = ("quant", "news", "event", "profit", "ml", "ai")

    by_tag: dict[str, Any] = {}
    for tag in tags:
        by_tag[tag] = _aggregate_horizons(
            outcomes,
            filter_fn=lambda o, t=tag: t in {str(s).lower() for s in (o.get("candidate_sources") or [])},
            horizons=horizons,
            minimum_sample=minimum_sample,
        )

    by_primary: dict[str, Any] = {}
    primaries = {str(o.get("primary_source") or "unknown") for o in outcomes}
    for p in sorted(primaries):
        by_primary[p] = _aggregate_horizons(
            outcomes,
            filter_fn=lambda o, pr=p: str(o.get("primary_source") or "unknown") == pr,
            horizons=horizons,
            minimum_sample=minimum_sample,
        )

    return {
        "available": bool(outcomes),
        "horizons": horizons,
        "minimum_sample": minimum_sample,
        "by_tag": by_tag,
        "by_primary_source": by_primary,
        "cohorts": {
            "news_vs_non_news": cohort_compare(outcomes, tag="news", cfg=cfg),
            "event_vs_non_event": cohort_compare(outcomes, tag="event", cfg=cfg),
        },
    }


def cohort_compare(
    outcomes: list[dict[str, Any]],
    *,
    tag: str,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compare outcomes with vs without a discovery tag."""
    acfg = attribution_cfg(cfg)
    horizons = list(acfg.get("horizons_days") or [1, 5, 10, 20])
    minimum_sample = int(acfg.get("minimum_sample") or 5)
    tag_l = tag.lower()

    def _has(o: dict[str, Any]) -> bool:
        return tag_l in {str(s).lower() for s in (o.get("candidate_sources") or [])}

    with_tag = _aggregate_horizons(outcomes, filter_fn=_has, horizons=horizons, minimum_sample=minimum_sample)
    without_tag = _aggregate_horizons(
        outcomes, filter_fn=lambda o: not _has(o), horizons=horizons, minimum_sample=minimum_sample
    )
    incremental: dict[str, Any] = {}
    for h in horizons:
        h_key = str(h)
        w = (with_tag.get(h_key) or {})
        wo = (without_tag.get(h_key) or {})
        if w.get("insufficient_sample") or wo.get("insufficient_sample"):
            incremental[h_key] = {"insufficient_sample": True}
            continue
        w_sel = ((w.get("selection_alpha") or {}).get("mean"))
        wo_sel = ((wo.get("selection_alpha") or {}).get("mean"))
        if w_sel is not None and wo_sel is not None:
            incremental[h_key] = {
                "insufficient_sample": False,
                "incremental_selection_alpha": float(w_sel) - float(wo_sel),
            }
        else:
            w_m = ((w.get("market_alpha") or {}).get("mean"))
            wo_m = ((wo.get("market_alpha") or {}).get("mean"))
            if w_m is not None and wo_m is not None:
                incremental[h_key] = {
                    "insufficient_sample": False,
                    "incremental_market_alpha": float(w_m) - float(wo_m),
                }
            else:
                incremental[h_key] = {"insufficient_sample": True, "note": "no_alpha_metrics"}

    return {
        "tag": tag,
        "with_tag": with_tag,
        "without_tag": without_tag,
        "incremental": incremental,
    }
