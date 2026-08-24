"""V5.4 unified attribution + discovery primary source."""

from __future__ import annotations

from ashare.research.outcome_truth import apply_primary_truth, PRIMARY_PAPER_FILL
from ashare.research.signal_attribution import (
    discovery_primary,
    enrich_outcome_sources,
    news_discovery_cohort,
    news_evidence_cohort,
    resolve_primary_source,
)
from ashare.research.unified_attribution import build_unified_record


def test_discovery_primary_not_entry_source():
    o = {
        "candidate_sources": ["event", "quant"],
        "horizons": {"5": {"actual_return": 0.01}},
        "execution": {"available": True, "horizons_from_fill": {"5": {"actual_return": 0.02}}},
    }
    apply_primary_truth([o])
    enrich_outcome_sources(o, {"research": {"attribution": {"primary_source_priority": ["event", "quant"]}}})
    assert o["primary_entry_source"] == PRIMARY_PAPER_FILL
    assert discovery_primary(o) == "event"


def test_unified_record_prices():
    rep = {"symbol": "600000.SH", "research_id": "R1", "decision": {"research_rating": "BUY"}}
    o = {
        "symbol": "600000.SH",
        "research_id": "R1",
        "signal_price": 10.0,
        "primary_horizons": {"5": {"actual_return": 0.01, "selection_alpha": 0.005}},
        "candidate_sources": ["news"],
    }
    enrich_outcome_sources(o, {"research": {"attribution": {"minimum_sample_size": 30}}})
    row = build_unified_record(rep, o, {"research": {}})
    assert row["signal_price"]["available"] is True
    assert row["discovery_primary_source"] == "news"
    assert row["horizons"]["5"]["available"] is True


def test_news_discovery_vs_evidence():
    outcomes = []
    for i in range(35):
        outcomes.append(
            {
                "candidate_sources": ["news"],
                "discovery_primary_source": "news",
                "secondary_sources": [],
                "primary_horizons": {"5": {"actual_return": 0.02, "selection_alpha": 0.02}},
            }
        )
    for i in range(35):
        outcomes.append(
            {
                "candidate_sources": ["event", "news"],
                "discovery_primary_source": "event",
                "secondary_sources": ["news"],
                "primary_horizons": {"5": {"actual_return": 0.01, "selection_alpha": 0.01}},
            }
        )
    cfg = {"research": {"attribution": {"minimum_sample_size": 30, "horizons_days": [5]}}}
    disc = news_discovery_cohort(outcomes, cfg)
    ev = news_evidence_cohort(outcomes, cfg)
    assert disc["tag"] == "news_discovery"
    assert ev["tag"] == "news_evidence"
    assert disc["with_tag"]["5"]["insufficient_sample"] is False
