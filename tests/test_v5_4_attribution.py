"""V5.4 Signal attribution tests."""

from __future__ import annotations

from ashare.research.signal_attribution import (
    cohort_compare,
    horizon_metrics,
    resolve_primary_source,
    summarize_signal_attribution,
)


def test_primary_source_priority():
    r = resolve_primary_source(["quant", "event", "profit"], ["profit", "event", "quant"])
    assert r["primary_source"] == "profit"
    assert "event" in r["secondary_sources"]
    assert "quant" in r["secondary_sources"]


def test_primary_source_unknown_when_empty():
    r = resolve_primary_source([], ["profit", "event"])
    assert r["primary_source"] == "unknown"


def test_horizon_metrics_uses_primary_horizons():
    o = {
        "primary_horizons": {
            "5": {"actual_return": 0.05, "market_alpha": 0.02, "selection_alpha": 0.03}
        },
        "horizons": {"5": {"actual_return": 0.99}},
    }
    m = horizon_metrics(o, 5)
    assert m is not None
    assert m["realized_return"] == 0.05
    assert m["market_alpha"] == 0.02


def test_insufficient_sample():
    outcomes = [
        {
            "candidate_sources": ["event"],
            "primary_source": "event",
            "primary_horizons": {"5": {"actual_return": 0.01, "selection_alpha": 0.005}},
        }
    ]
    cfg = {"_root": ".", "research": {"attribution": {"minimum_sample": 5, "horizons_days": [5]}}}
    s = summarize_signal_attribution(outcomes, cfg)
    assert s["by_tag"]["event"]["5"]["insufficient_sample"] is True


def test_cohort_compare_news():
    outcomes = [
        {"candidate_sources": ["news"], "primary_horizons": {"5": {"selection_alpha": 0.02}}},
        {"candidate_sources": ["quant"], "primary_horizons": {"5": {"selection_alpha": 0.01}}},
    ] * 6
    cfg = {"research": {"attribution": {"minimum_sample": 5, "horizons_days": [5]}}}
    c = cohort_compare(outcomes, tag="news", cfg=cfg)
    assert c["tag"] == "news"
    assert "with_tag" in c
