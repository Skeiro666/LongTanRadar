"""V5.4 news discovery alpha cohorts."""

from __future__ import annotations

from ashare.research.signal_attribution import news_discovery_cohort


def test_news_primary_only():
    outcomes = [
        {"discovery_primary_source": "news", "secondary_sources": [], "primary_horizons": {"5": {"actual_return": 0.03, "selection_alpha": 0.03}}}
    ] * 35 + [
        {"discovery_primary_source": "quant", "secondary_sources": [], "primary_horizons": {"5": {"actual_return": 0.01, "selection_alpha": 0.01}}}
    ] * 35
    c = news_discovery_cohort(outcomes, {"research": {"attribution": {"minimum_sample_size": 30, "horizons_days": [5]}}})
    incr = (c.get("incremental") or {}).get("5") or {}
    assert incr.get("insufficient_sample") is False
    assert incr.get("incremental_selection_alpha") is not None
