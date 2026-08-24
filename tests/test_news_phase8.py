"""V5 Phase 8 �?news cluster, hypothesis, evidence registry."""

from __future__ import annotations

from ashare.news.cluster import cluster_timeline_events
from ashare.news.evidence_registry import EvidenceRegistry
from ashare.news.models import RawNews, make_id, title_hash
from ashare.research.hypothesis import ResearchHypothesisEngine


def test_cluster_by_symbol_and_type():
    events = [
        {"symbol": "600000.SH", "event_type": "ORDER", "direction": "BULLISH", "impact_score": 0.8, "title": "A", "event_id": "E1", "news_id": "N1"},
        {"symbol": "600000.SH", "event_type": "ORDER", "direction": "BULLISH", "impact_score": 0.5, "title": "B", "event_id": "E2", "news_id": "N2"},
        {"symbol": "000001.SZ", "event_type": "ORDER", "direction": "BULLISH", "impact_score": 0.6, "title": "C", "event_id": "E3", "news_id": "N3"},
    ]
    clusters = cluster_timeline_events(events, by_symbol=True)
    assert len(clusters) == 2
    sh = next(c for c in clusters if c["symbol"] == "600000.SH")
    assert sh["n_sources"] == 2
    assert len(sh["facts"]) >= 1
    assert len(sh["evidence_ids"]) >= 2


def test_investment_hypothesis_schema():
    n = RawNews(
        id=make_id("N"),
        source="sina",
        title="公司签订重大合同订单",
        fetched_at="2026-08-20T00:00:00+00:00",
        title_hash=title_hash("公司签订重大合同订单"),
    )
    from ashare.news.extract import extract_events

    ev = extract_events(n, symbol="000786.SZ", relevance=0.9)[0]
    h = ResearchHypothesisEngine().from_event(ev, news=n)
    inv = h.to_investment_hypothesis()
    assert "mechanism" in inv
    assert "validation" in inv
    assert "invalidation" in inv
    assert inv["layers"]["FACT"] != inv["layers"]["INFERENCE"]


def test_evidence_registry_stable_ids(tmp_path):
    reg = EvidenceRegistry({"_root": str(tmp_path)})
    k = EvidenceRegistry.evidence_key("N1", "测试标题")
    e1 = reg.register(key=k, title="测试标题", news_id="N1", persist=True)
    e2 = reg.register(key=k, title="测试标题", news_id="N1", persist=False)
    assert e1 == e2
    assert e1.startswith("E")
