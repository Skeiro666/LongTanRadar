from __future__ import annotations

from datetime import datetime, timezone

from ashare.news.linking import LLM_INFERENCE_MAX_CONF, codes_in_text, link_entities_open, llm_inference_entities
from ashare.news.models import RawNews, make_id, title_hash
from ashare.news.opportunity import NewsOpportunityEngine


def _n(title: str, **kw) -> RawNews:
    now = datetime.now(timezone.utc).isoformat()
    return RawNews(
        id=kw.get("id") or make_id("N"),
        source="sina",
        title=title,
        fetched_at=now,
        summary=kw.get("summary", title),
        published_at=kw.get("published_at", "2026-08-20 10:00:00"),
        title_hash=title_hash(title),
        media="新浪财经",
    )


def test_codes_in_text_skips_dates():
    assert codes_in_text("20260821 市场综述") == []
    assert "000786.SZ" in codes_in_text("北新建材000786签订重大合同")
    assert "600519.SH" in codes_in_text("贵州茅台 600519.SH 回购")


def test_opportunity_events_without_symbol_input():
    eng = NewsOpportunityEngine({"_root": "."})
    out = eng.discover(
        as_of=datetime(2026, 8, 20, 23, 59, tzinfo=timezone.utc),
        persist=False,
        news=[
            _n("水泥行业价格波动"),
            _n("000786签订重大合同订单金额10亿"),
        ],
    )
    assert out["available"] is True
    assert out["n_events"] >= 1
    assert any(e["event_type"] == "ORDER" for e in out["events"])
    assert any(c["symbol"] == "000786.SZ" for c in out["news_candidates"])
    for c in out["news_candidates"]:
        assert "BUY" not in c.get("status", "")
        assert c["candidate_source"] == "news"
        assert c["mapping_method"] == "code"
    assert any(r.get("reject_reason") in {"NOT_ENOUGH_EVIDENCE", "INDUSTRY_MAP_UNAVAILABLE"} for r in out["rejected"])


def test_name_map_discovers_stock_without_code():
    eng = NewsOpportunityEngine({"_root": "."})
    out = eng.discover(
        persist=False,
        news=[_n("北新建材签订重大合同订单")],
        name_map={"000786.SZ": "北新建材"},
        aliases={},
    )
    assert any(c["symbol"] == "000786.SZ" and c["mapping_method"] == "official_name" for c in out["news_candidates"])
    hyp = (out["news_candidates"][0].get("research_hypotheses") or [{}])[0]
    assert hyp.get("type") == "HYPOTHESIS"
    assert hyp.get("layers", {}).get("FACT")
    assert all(c.get("mapping_method") != "llm_inference" for c in out["news_candidates"])


def test_alias_maps_maotai():
    eng = NewsOpportunityEngine({"_root": "."})
    out = eng.discover(
        persist=False,
        news=[_n("茅台公告回购股份")],
        name_map={},
        aliases={"茅台": "600519.SH"},
    )
    assert any(c["symbol"] == "600519.SH" and c["mapping_method"] == "alias" for c in out["news_candidates"])


def test_llm_inference_capped_and_not_high_confidence():
    n = _n("某材料价格大幅上涨")
    ents = llm_inference_entities(n, [{"symbol": "000786.SZ", "name": "北新建材", "confidence": 0.99}])
    assert ents[0].mapping_method == "llm_inference"
    assert ents[0].confidence <= LLM_INFERENCE_MAX_CONF
    rule = link_entities_open(n, name_map={"000786.SZ": "北新建材"})
    # title has no 北新建材 — rule empty; llm must stay below official_name level 0.88
    assert not rule or rule[0].confidence > ents[0].confidence
    n2 = _n("北新建材签订订单")
    rule2 = link_entities_open(n2, name_map={"000786.SZ": "北新建材"})
    assert rule2[0].confidence > ents[0].confidence


def test_future_news_not_in_discovery_when_injected_filtered():
    from ashare.news.package import filter_asof

    as_of = datetime(2026, 8, 20, tzinfo=timezone.utc)
    items = [
        _n("旧订单", published_at="2026-08-19 09:00:00"),
        _n("未来订单", published_at="2026-08-21 09:00:00"),
    ]
    kept = filter_asof(items, as_of)
    eng = NewsOpportunityEngine({"_root": "."})
    out = eng.discover(as_of=as_of, persist=False, news=kept)
    titles = [e["title"] for e in out["events"]]
    assert any("旧订单" in t for t in titles)
    assert not any("未来订单" in t for t in titles)


def test_discovery_fetch_failure_does_not_raise(monkeypatch):
    eng = NewsOpportunityEngine({"_root": "."})

    def boom(**kwargs):
        raise RuntimeError("network down")

    monkeypatch.setattr(eng.intel, "collect_latest", boom)
    out = eng.discover(persist=False)
    assert out["available"] is False
    assert out["news_candidates"] == []
    assert out["events"] == []
