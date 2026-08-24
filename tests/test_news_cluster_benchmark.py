from __future__ import annotations

import pandas as pd

from ashare.news.cluster import cluster_timeline_events, compact_news_headlines
from ashare.research.benchmark import equal_weight_benchmark_returns


def test_cluster_merges_same_event_type():
    events = [
        {"event_type": "ORDER", "direction": "BULLISH", "impact_score": 0.8, "title": "订单A", "event_id": "E1"},
        {"event_type": "ORDER", "direction": "BULLISH", "impact_score": 0.5, "title": "订单B", "event_id": "E2"},
        {"event_type": "REGULATORY", "direction": "BEARISH", "impact_score": 0.6, "title": "监管", "event_id": "E3"},
    ]
    clusters = cluster_timeline_events(events)
    assert len(clusters) == 2
    order = next(c for c in clusters if c["event_type"] == "ORDER")
    assert order["n_sources"] == 2
    assert len(order["evidence_ids"]) == 2


def test_compact_news_dedupes_titles():
    rows = [
        {"title": "公司签订重大合同订单金额10亿元"},
        {"title": "公司签订重大合同订单金额10亿元"},
        {"title": "另一则新�?},
    ]
    out = compact_news_headlines(rows, max_items=5)
    assert len(out) == 2


def test_equal_weight_benchmark():
    dates = pd.bdate_range("2024-01-02", periods=10)
    panel = {
        "A": pd.DataFrame({"date": dates, "close": [10.0] * 5 + [11.0] * 5}),
        "B": pd.DataFrame({"date": dates, "close": [20.0] * 5 + [21.0] * 5}),
    }
    pack = equal_weight_benchmark_returns(panel, dates[4], horizons=[5])
    assert pack["n_symbols"] == 2
    assert pack["returns"]["5"] is not None
