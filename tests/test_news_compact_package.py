from __future__ import annotations

from ashare.news.compact import build_compact_news_package


def test_compact_structure_no_raw_dump():
    intel = [
        {
            "news_id": "N1",
            "event_type": "order",
            "direction": "positive",
            "importance": 0.9,
            "news_intelligence_score": 0.85,
            "summary": "签订重大合同",
            "evidence": ["合同金额10亿"],
        }
    ]
    events = [
        {
            "event_id": "E1",
            "event_type": "ORDER",
            "normalized_event_type": "order",
            "evidence_direction": "positive",
            "title": "重大合同",
        }
    ]
    pkg = build_compact_news_package("000786.SZ", events, intel, net_event_score=0.5)
    assert pkg["symbol"] == "000786.SZ"
    assert pkg["positive"]
    assert pkg["top_evidence"]
    assert "events" in pkg
    assert "last_7d" not in pkg
    assert "legacy_headlines" not in pkg


def test_snippet_only_for_major():
    intel = [{"event_type": "other", "direction": "neutral", "importance": 0.2, "summary": "x" * 200}]
    pkg = build_compact_news_package("000786.SZ", [], intel)
    pos = pkg.get("positive") or []
    neg = pkg.get("negative") or []
    all_items = pos + neg + (pkg.get("top_evidence") or [])
    for item in all_items:
        assert "snippet" not in item or len(str(item.get("snippet") or "")) <= 120
