from __future__ import annotations

from ashare.news.extract import extract_events
from ashare.news.models import RawNews, make_id, title_hash
from ashare.research.hypothesis import ResearchHypothesisEngine


def test_hypothesis_layers_not_disguised_as_fact():
    n = RawNews(
        id=make_id("N"),
        source="sina",
        title="公司签订重大合同订单",
        fetched_at="2026-08-20T00:00:00+00:00",
        summary="中标10�?,
        title_hash=title_hash("公司签订重大合同订单"),
    )
    evs = extract_events(n, symbol="000786.SZ", relevance=0.9)
    order = next(e for e in evs if e.event_type == "ORDER")
    h = ResearchHypothesisEngine().from_event(order, news=n).to_dict()
    assert h["type"] == "HYPOTHESIS"
    assert h["layers"]["FACT"] == "公司签订重大合同订单"
    assert h["layers"]["FACT"] != h["layers"]["INFERENCE"]
    assert h["layers"]["HYPOTHESIS"] != h["layers"]["FACT"]
    assert "可能" in h["layers"]["INFERENCE"] or "如果" in h["hypothesis"]
    assert len(h["validation_questions"]) >= 3
    assert "BUY" not in h["hypothesis"]
    assert order.facts and order.inferences


def test_price_increase_template():
    n = RawNews(
        id=make_id("N"),
        source="sina",
        title="产品涨价通知",
        fetched_at="2026-08-20T00:00:00+00:00",
        title_hash=title_hash("产品涨价通知"),
    )
    evs = extract_events(n, symbol="600519.SH", relevance=0.8)
    ev = next(e for e in evs if e.event_type == "PRICE_INCREASE")
    h = ResearchHypothesisEngine().from_event(ev, news=n)
    assert "毛利" in h.hypothesis
    assert any("占比" in q for q in h.validation_questions)
