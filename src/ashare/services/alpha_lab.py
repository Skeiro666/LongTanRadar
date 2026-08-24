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
        "lab_summary": pack.get("lab_summary") or build_lab_summary(pack),
        "notification_llm_cost": 0,
    }
