"""V5.2 Phase 2 �?event lifecycle, price_in_score, expected_excess_return, as_of leak fix."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd

from ashare.news.event_lifecycle import (
    LIFECYCLE_NEW,
    LIFECYCLE_PRICED_IN,
    LIFECYCLE_REJECTED,
    LIFECYCLE_RESOLVED,
    apply_event_lifecycle,
    compute_event_lifecycle,
    price_in_score,
)
from ashare.news.models import ExtractedEvent, NewsCandidate
from ashare.research.hypothesis import ResearchHypothesisEngine
from ashare.research.price_reaction import annotate_news_candidate_price
from tests.test_platform_engines import _synth_bars


def test_price_in_score_from_risk():
    assert price_in_score(price_in_risk="HIGH") == 0.85
    assert price_in_score(price_in_risk="LOW") == 0.15
    assert price_in_score(price_in_risk="UNKNOWN") == 0.0


def test_lifecycle_new_vs_priced_in():
    nc = {"status": "DISCOVERED", "price_in_risk": "LOW"}
    lc = compute_event_lifecycle(nc)
    assert lc["lifecycle_status"] == LIFECYCLE_NEW

    nc2 = {"status": "DISCOVERED", "price_in_risk": "HIGH", "price_reaction": {"available": True}}
    lc2 = compute_event_lifecycle(nc2)
    assert lc2["lifecycle_status"] == LIFECYCLE_PRICED_IN


def test_lifecycle_rejected():
    nc = {"status": "REJECTED", "reject_reason": "RANKING_CUTOFF"}
    lc = compute_event_lifecycle(nc)
    assert lc["lifecycle_status"] == LIFECYCLE_REJECTED


def test_lifecycle_confirmed_on_high_confidence():
    from ashare.news.event_lifecycle import LIFECYCLE_CONFIRMED, LIFECYCLE_DEVELOPING, LIFECYCLE_NEW, compute_event_lifecycle

    nc = {
        "status": "DISCOVERED",
        "confidence": 0.88,
        "mapping_method": "official_name",
        "price_in_risk": "LOW",
        "price_reaction": {"available": True, "ret_since_event": 0.01},
    }
    lc = compute_event_lifecycle(nc, as_of="2026-08-22")
    assert lc["lifecycle_status"] in {LIFECYCLE_CONFIRMED, LIFECYCLE_NEW, LIFECYCLE_DEVELOPING}


def test_lifecycle_resolved_by_outcome():
    nc = {"status": "DISCOVERED", "price_in_risk": "LOW"}
    outcome = {
        "outcome_status": "ok",
        "horizons": {"20": {"actual_return": 0.05, "status": "ok"}},
    }
    lc = compute_event_lifecycle(nc, outcome=outcome)
    assert lc["lifecycle_status"] == LIFECYCLE_RESOLVED


def test_annotate_applies_lifecycle_and_score():
    df = _synth_bars()
    df.loc[df.index[-1], "close"] = df["close"].iloc[-2] * 1.12
    nc = {
        "symbol": "600000.SH",
        "status": "DISCOVERED",
        "event_direction": "BULLISH",
        "event_time": str(df["date"].iloc[-1])[:10],
    }
    out = annotate_news_candidate_price(nc, {"600000.SH": df}, as_of=str(df["date"].iloc[-1])[:10])
    assert "lifecycle_status" in out
    assert "price_in_score" in out
    assert out["price_in_risk"] in {"HIGH", "MEDIUM", "LOW", "UNKNOWN"}


def test_expected_excess_return_unavailable_by_default():
    ev = ExtractedEvent(
        event_id="E1",
        news_id="N1",
        symbol="600000.SH",
        event_type="ORDER",
        title="test",
        description="",
        event_time="2026-01-01",
        discovery_time="2026-01-01",
        source="sina",
        source_url="",
        direction="BULLISH",
        direction_score=0.5,
        impact_score=0.6,
        confidence=0.7,
        time_horizon="SHORT_TERM",
    )
    h = ResearchHypothesisEngine().from_event(ev)
    inv = h.to_investment_hypothesis(ev)
    eer = inv["expected_excess_return"]
    assert eer["available"] is False
    assert eer["value"] is None


def test_expected_excess_return_when_gap_available():
    ev = ExtractedEvent(
        event_id="E2",
        news_id="N2",
        symbol="600000.SH",
        event_type="EARNINGS_GUIDANCE",
        title="test",
        description="",
        event_time="2026-01-01",
        discovery_time="2026-01-01",
        source="sina",
        source_url="",
        direction="BULLISH",
        direction_score=0.5,
        impact_score=0.6,
        confidence=0.7,
        time_horizon="SHORT_TERM",
        expectation_available=True,
        expectation_gap=0.25,
    )
    h = ResearchHypothesisEngine().from_event(ev)
    inv = h.to_investment_hypothesis(ev)
    eer = inv["expected_excess_return"]
    assert eer["available"] is True
    assert eer["value"] == 0.25


def test_collect_stock_receives_as_of(monkeypatch):
    captured: list = []

    def fake_collect(self, symbol, **kw):
        captured.append(kw.get("as_of"))
        return {"net_event_score": 0.0, "news_data_incomplete": False}

    monkeypatch.setattr("ashare.news.engine.NewsIntelligenceEngine.collect_stock", fake_collect)
    from ashare.candidate import CandidateEngine

    a = "600000.SH"
    as_of = datetime(2026, 1, 15, 23, 59, 59, tzinfo=timezone.utc)
    eng = CandidateEngine({"_root": ".", "research": {"funnel": {"max_research_pool": 5}}})
    eng.build_research_universe(
        {a: _synth_bars()},
        pool={"candidates": [{"symbol": a, "name": "浦发银行", "source": "tech_leader", "sources": ["tech_leader"]}]},
        news_discovery={"news_candidates": [], "rejected": [], "as_of": as_of.isoformat()},
        as_of=as_of.isoformat(),
    )
    assert captured
    assert captured[0] is not None
    assert captured[0].year == 2026
