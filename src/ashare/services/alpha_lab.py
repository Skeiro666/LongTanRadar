"""V5.4 Alpha Lab — evidence dashboard (Measurement > Features)."""

from __future__ import annotations

from typing import Any

from ashare.research.lab_summary import build_lab_summary
from ashare.research.signal_attribution import minimum_sample_size, source_status_label


def _window_days(window: str) -> int | None:
    w = (window or "all").lower().strip()
    if w in {"7d", "7"}:
        return 7
    if w in {"30d", "30"}:
        return 30
    if w in {"90d", "90"}:
        return 90
    return None


def _source_row(
    source: str,
    horizons: dict[str, Any],
    *,
    min_n: int,
    cost: float = 0.0,
    incremental: float | None = None,
) -> dict[str, Any]:
    h1 = horizons.get("1") or {}
    h5 = horizons.get("5") or {}
    h10 = horizons.get("10") or {}
    h20 = horizons.get("20") or {}
    n = int(h5.get("sample_count") or 0)
    sel5 = (h5.get("selection_alpha") or {}).get("mean") if not h5.get("insufficient_sample") else None
    sel10 = (h10.get("selection_alpha") or {}).get("mean") if not h10.get("insufficient_sample") else None
    sel20 = (h20.get("selection_alpha") or {}).get("mean") if not h20.get("insufficient_sample") else None
    sel1 = (h1.get("selection_alpha") or {}).get("mean") if not h1.get("insufficient_sample") else None
    med = (h5.get("selection_alpha") or {}).get("median") if not h5.get("insufficient_sample") else None
    wr = (h5.get("selection_alpha") or {}).get("win_rate") if not h5.get("insufficient_sample") else None
    status = h5.get("status") or source_status_label(sel5, sample_count=n, minimum_sample=min_n, incremental=incremental)
    return {
        "source": source,
        "sample_count": n,
        "t1_alpha": sel1,
        "t5_alpha": sel5,
        "t10_alpha": sel10,
        "t20_alpha": sel20,
        "win_rate": wr,
        "median_return": med,
        "cost_usd": cost,
        "incremental_alpha": incremental,
        "status": status,
    }


def _excess_mean(arm: dict[str, Any] | None, horizon: str) -> float | None:
    if not arm:
        return None
    h = arm.get(horizon) or {}
    if h.get("status") == "INSUFFICIENT_SAMPLE":
        return None
    ex = h.get("excess_return") or {}
    return ex.get("mean")


def _arm_row(name: str, label: str, arm: dict[str, Any], baseline: dict[str, Any], min_n: int) -> dict[str, Any]:
    rows: dict[str, Any] = {"id": name, "label": label, "horizons": {}}
    for h in ("1", "5", "10", "20"):
        block = arm.get(h) or {}
        base = baseline.get(h) or {}
        ex = _excess_mean(arm, h)
        base_ex = _excess_mean(baseline, h)
        rows["horizons"][h] = {
            "sample_count": block.get("sample_count"),
            "status": block.get("status"),
            "excess_return_mean": ex,
            "hit_rate": (block.get("excess_return") or {}).get("win_rate") or block.get("hit_rate"),
            "max_drawdown": (block.get("excess_return") or {}).get("max_drawdown"),
            "delta_vs_baseline": (ex - base_ex) if ex is not None and base_ex is not None else None,
            "baseline_excess_return_mean": base_ex,
        }
    h5 = arm.get("5") or {}
    rows["sample_count"] = h5.get("sample_count") or 0
    rows["status"] = h5.get("status") or (
        "INSUFFICIENT_SAMPLE" if rows["sample_count"] < min_n else "OK"
    )
    return rows


def _calibration_chart(cal: dict[str, Any], field: str) -> list[dict[str, Any]]:
    block = cal.get(field) or {}
    series: list[dict[str, Any]] = []
    for b in block.get("buckets") or []:
        h10 = (b.get("horizons") or {}).get("10") or {}
        series.append(
            {
                "bucket": b.get("range"),
                "sample_count": h10.get("sample_count"),
                "t10_excess_return": h10.get("excess_return_mean"),
                "status": h10.get("status"),
            }
        )
    return series


def build_experiment_lab(news_ablation: dict[str, Any], *, min_n: int) -> dict[str, Any]:
    arms = news_ablation.get("arms") or {}
    baseline = arms.get("no_news") or {}
    labels = {
        "no_news": "No News",
        "evidence_only": "News Evidence",
        "discovery_only": "News Discovery",
        "discovery_and_evidence": "News Discovery + Evidence",
        "news_plus_council": "News + Council",
    }
    experiments = [
        _arm_row(name, labels.get(name, name), arm, baseline, min_n)
        for name, arm in arms.items()
        if name != "no_news"
    ]
    return {
        "baseline": "no_news",
        "baseline_label": labels["no_news"],
        "baseline_row": _arm_row("no_news", labels["no_news"], baseline, baseline, min_n),
        "experiments": experiments,
    }


def build_performance_dashboard(news_alpha: dict[str, Any], min_n: int) -> list[dict[str, Any]]:
    lanes = [
        ("news_discovery_alpha", "News Discovery"),
        ("news_evidence_alpha", "News Evidence"),
        ("news_only_alpha", "News Only"),
        ("news_factor_alpha", "News + Factor"),
        ("news_council_alpha", "News + Council"),
    ]
    rows: list[dict[str, Any]] = []
    for key, label in lanes:
        hz = news_alpha.get(key) or {}
        h5 = hz.get("5") or {}
        h10 = hz.get("10") or {}
        rows.append(
            {
                "lane": label,
                "sample_count": h5.get("sample_count") or h10.get("sample_count") or 0,
                "t5_excess_return": _excess_mean(hz, "5"),
                "t10_excess_return": _excess_mean(hz, "10"),
                "t5_status": h5.get("status"),
                "t10_status": h10.get("status"),
                "minimum_sample": min_n,
            }
        )
    return rows


def build_alpha_lab(cfg: dict[str, Any] | None = None, *, window: str = "all") -> dict[str, Any]:
    from ashare.research.tracking import ReviewEngine
    from ashare.services.research import latest_research

    cfg = cfg or {}
    days = _window_days(window)
    engine = ReviewEngine(cfg)
    if days:
        outcomes = engine.load_outcomes_window(days=days)
        data = latest_research(cfg) or {}
        pack = dict(data.get("research_outcomes") or {})
        if outcomes:
            from ashare.research.signal_attribution import enrich_outcome_sources, summarize_signal_attribution

            for o in outcomes:
                enrich_outcome_sources(o, cfg)
            pack["signal_attribution"] = summarize_signal_attribution(outcomes, cfg)
            pack["outcomes"] = outcomes
    else:
        data = latest_research(cfg) or {}
        pack = dict(data.get("research_outcomes") or {})
        outcomes = list(pack.get("outcomes") or [])

    min_n = minimum_sample_size(cfg)
    sig = pack.get("signal_attribution") or {}
    source_rows: list[dict[str, Any]] = []

    if sig.get("profit_data_unavailable"):
        source_rows.append(
            {
                "source": "profit",
                "sample_count": 0,
                "status": "DATA_UNAVAILABLE",
                "t1_alpha": None,
                "t5_alpha": None,
                "t10_alpha": None,
                "t20_alpha": None,
                "win_rate": None,
                "median_return": None,
                "cost_usd": 0,
                "incremental_alpha": None,
            }
        )

    for src in ("event", "profit", "quant", "news"):
        if src == "profit" and sig.get("profit_data_unavailable"):
            continue
        hz = (sig.get("by_primary_source") or {}).get(src) or {}
        if not hz:
            continue
        source_rows.append(_source_row(src.capitalize(), hz, min_n=min_n))

    ml_ab = pack.get("ml_ablation") or {}
    if ml_ab.get("available"):
        h5 = (ml_ab.get("horizons") or {}).get("5") or {}
        source_rows.append(
            {
                "source": "ML",
                "sample_count": h5.get("sample_count") or 0,
                "t5_alpha": (h5.get("with_ml") or {}).get("mean"),
                "t10_alpha": ((ml_ab.get("horizons") or {}).get("10") or {}).get("with_ml", {}).get("mean"),
                "t20_alpha": ((ml_ab.get("horizons") or {}).get("20") or {}).get("with_ml", {}).get("mean"),
                "incremental_alpha": h5.get("ml_incremental_alpha"),
                "cost_usd": 0,
                "status": h5.get("status") or "UNPROVEN",
                "win_rate": (h5.get("with_ml") or {}).get("win_rate"),
                "median_return": (h5.get("with_ml") or {}).get("median"),
            }
        )

    ab = pack.get("ai_council_ablation") or {}
    if ab.get("available"):
        h5 = (ab.get("horizons") or {}).get("5") or {}
        incr = h5.get("ai_incremental_alpha")
        source_rows.append(
            {
                "source": "AI",
                "sample_count": h5.get("sample_count") or 0,
                "t5_alpha": (h5.get("with_council") or {}).get("mean"),
                "t10_alpha": ((ab.get("horizons") or {}).get("10") or {}).get("with_council", {}).get("mean"),
                "t20_alpha": ((ab.get("horizons") or {}).get("20") or {}).get("with_council", {}).get("mean"),
                "incremental_alpha": incr,
                "cost_usd": ab.get("llm_cost_usd"),
                "efficiency": ab.get("ai_efficiency"),
                "status": ab.get("status") or "UNPROVEN",
                "win_rate": (h5.get("with_council") or {}).get("win_rate"),
                "median_return": (h5.get("with_council") or {}).get("median"),
            }
        )

    routing = pack.get("token_efficiency") or data.get("gate_summary", {}).get("ai_routing") or {}

    from ashare.research.news_ablation import build_news_ablation
    from ashare.research.news_alpha import build_news_alpha_attribution
    from ashare.research.news_calibration import build_news_calibration
    from ashare.research.token_attribution import summarize_token_attribution

    quant_top_n = set(
        data.get("quant_top_n_symbols")
        or (data.get("candidate_union") or {}).get("quant_top_n_symbols")
        or []
    )
    news_alpha = build_news_alpha_attribution(outcomes, cfg, quant_top_n=quant_top_n)
    news_calibration = build_news_calibration(outcomes, cfg)
    news_ablation = build_news_ablation(outcomes, cfg)
    token_stats = summarize_token_attribution(cfg)
    experiment_lab = build_experiment_lab(news_ablation, min_n=min_n)
    calibration_charts = {
        "news_score": _calibration_chart(news_calibration, "score"),
        "importance": _calibration_chart(news_calibration, "importance"),
        "novelty": _calibration_chart(news_calibration, "novelty"),
    }
    performance_dashboard = build_performance_dashboard(news_alpha, min_n)

    return {
        "available": bool(source_rows or pack.get("available")),
        "window": window,
        "minimum_sample_size": min_n,
        "as_of": data.get("as_of"),
        "source_alpha": source_rows,
        "modules": source_rows,
        "signal_attribution": sig,
        "ai_council_ablation": ab,
        "ml_ablation": ml_ab,
        "calibration": pack.get("calibration"),
        "token_efficiency": pack.get("token_efficiency"),
        "ai_routing": routing,
        "news_discovery": ((sig.get("cohorts") or {}).get("news_discovery")),
        "news_evidence": ((sig.get("cohorts") or {}).get("news_evidence")),
        "news_alpha": news_alpha,
        "news_calibration": news_calibration,
        "news_ablation": news_ablation,
        "experiment_lab": experiment_lab,
        "performance_dashboard": performance_dashboard,
        "calibration_charts": calibration_charts,
        "token_stats": token_stats,
        "quant_top_n_symbols": sorted(quant_top_n),
        "news_ab_buckets": news_alpha.get("ab_buckets"),
        "news_token_stats": token_stats.get("local"),
        "cloud_token_stats": token_stats.get("cloud"),
        "token_saved_pct": token_stats.get("token_saved_pct"),
        "lab_summary": pack.get("lab_summary") or build_lab_summary(pack),
        "notification_llm_cost": 0,
    }
