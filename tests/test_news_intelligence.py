from __future__ import annotations

from datetime import datetime, timezone

from ashare.news.classify import classify_news
from ashare.news.common import unix_to_iso
from ashare.news.dedup import dedupe_news
from ashare.news.enrich import extract_for_news
from ashare.news.entity_resolve import resolve_entities_open
from ashare.news.expectation import expectation_gap
from ashare.news.extract import extract_events
from ashare.news.intel_score import news_intelligence_score
from ashare.news.linking import link_entities
from ashare.news.models import RawNews, make_id, title_hash
from ashare.news.package import filter_asof
from ashare.news.registry import build_providers
from ashare.news.schema import strip_trade_actions
from ashare.news.score import freshness_score, net_event_score, source_quality

from news_intel_fakes import FakeNewsClient, make_engine, sample_news


def _news(title: str, **kw) -> RawNews:
    now = datetime.now(timezone.utc).isoformat()
    return RawNews(
        id=kw.get("id") or make_id("N"),
        source=kw.get("source", "eastmoney"),
        title=title,
        fetched_at=now,
        summary=kw.get("summary", title),
        published_at=kw.get("published_at", now),
        url=kw.get("url", ""),
        source_id=kw.get("source_id", ""),
        title_hash=title_hash(title),
        media=kw.get("media", "东方财富"),
        query_symbol="000786.SZ",
    )


def test_dedup_title_and_url():
    a = _news("重大订单公告", url="http://x/a", source_id="1")
    b = _news("重大订单公告", url="http://x/a?x=1", source_id="2")
    c = _news("另一�?, url="http://x/b", source_id="3")
    out = dedupe_news([a, b, c])
    assert len(out) == 2


def test_entity_linking_not_assumed():
    n = _news("水泥行业价格波动")
    ents = link_entities(n, symbol="000786.SZ", name="北新建材")
    assert ents[0].confidence < 0.5
    assert ents[0].link_source == "query_weak"
    n2 = _news("北新建材000786获得重大订单")
    ents2 = link_entities(n2, symbol="000786.SZ", name="北新建材")
    assert ents2[0].confidence > 0.9
    n3 = _news("A股复盘：58只涨�?, summary="其中包括北新建材000786、维峰电子等")
    ents3 = link_entities(n3, symbol="000786.SZ", name="北新建材")
    assert ents3[0].link_source == "body_only"
    assert ents3[0].confidence < 0.5


def test_collect_stock_filters_query_weak(monkeypatch):
    from ashare.news.engine import NewsIntelligenceEngine

    good = _news("汉森制药002412发布半年�?, source="baidu")
    bad = _news("维峰电子2026年半年报", source="eastmoney")

    class FakeP:
        name = "fake"
        version = "fake_v1"

        def fetch_stock_news(self, symbol, *, name="", limit=20):
            return [good, bad]

    monkeypatch.setattr("ashare.news.llm_mapping.news_llm_client", lambda cfg: None)
    eng = NewsIntelligenceEngine({"_root": ".", "news": {"fetch": {"min_link_confidence": 0.5}}})
    monkeypatch.setattr(eng, "providers", [FakeP()])
    pkg = eng.collect_stock("002412.SZ", name="汉森制药", persist=False)
    titles = [x.get("title") for x in pkg.get("last_7d") or []]
    assert any("汉森制药" in t for t in titles)
    assert not any("维峰电子" in t for t in titles)
    assert pkg["link_filter"]["n_weak_dropped"] >= 1


def test_classify_and_extract_order():
    n = _news("公司签订重大合同订单")
    assert classify_news(n) == "ORDER"
    evs = extract_events(n, symbol="000786.SZ", relevance=0.9)
    assert any(e.event_type == "ORDER" for e in evs)
    assert evs[0].direction_score > 0
    assert evs[0].evidence_id == n.id


def test_expectation_gap_no_fabricate():
    g = expectation_gap()
    assert g["available"] is False
    assert g["gap"] is None
    g2 = expectation_gap(actual=0.35, consensus=0.20)
    assert g2["available"] is True
    assert g2["gap"] > 0


def test_net_score_conflict_not_naive_sum():
    e1 = extract_events(_news("业绩预增"), symbol="X", relevance=0.9)
    e2 = extract_events(_news("大股东减�?), symbol="X", relevance=0.9)
    for e in e1 + e2:
        e.relevance = 0.9
    s = net_event_score(e1 + e2)
    assert -1 <= s <= 1


def test_future_news_filtered():
    past = _news("旧闻", published_at="2026-01-01 00:00:00")
    future = _news("未来新闻", published_at="2026-12-31 00:00:00")
    as_of = datetime(2026, 8, 22, tzinfo=timezone.utc)
    kept = filter_asof([past, future], as_of)
    titles = [x.title for x in kept]
    assert "旧闻" in titles
    assert "未来新闻" not in titles


def test_unparsed_published_at_dropped_when_asof():
    bad = _news("无日�?, published_at="not-a-date")
    as_of = datetime(2026, 8, 20, tzinfo=timezone.utc)
    assert filter_asof([bad], as_of) == []
    assert len(filter_asof([bad], None)) == 1


def test_source_quality_a_vs_c():
    assert source_quality(_news("上交所公告", media="上交所")) == "A"
    assert source_quality(_news("市场传闻", media="某论�?)) in {"C", "D"}
    b = _news("订单", media="证券时报", source="baidu")
    assert source_quality(b) == "B"


def test_multi_provider_registry():
    names = [p.name for p in build_providers(["baidu", "eastmoney", "sina", "ths", "unknown"])]
    assert names == ["baidu", "eastmoney", "sina", "ths"]
    fallback = build_providers([])
    assert {p.name for p in fallback} >= {"baidu", "eastmoney"}


def test_unix_to_iso_and_iso_freshness():
    iso = unix_to_iso(1710000000)
    assert iso.startswith("2024-")
    assert freshness_score(iso) >= 0.1


def test_known_stock_news_still_calls_intelligence(tmp_path):
    n = sample_news("北新建材000786签订重大合同订单金额10�?)
    ents = resolve_entities_open(n, name_map={"000786.SZ": "北新建材"})
    client = FakeNewsClient()
    eng = make_engine(tmp_path, client)
    intel = extract_for_news(n, eng, ents, classification="ORDER")
    assert intel is not None
    assert client.calls >= 1
    assert intel["event_type"] == "order"
    assert 0 <= intel["news_intelligence_score"] <= 1
    assert "BUY" not in str(intel)


def test_intelligence_score_is_programmatic():
    s = news_intelligence_score(
        importance=0.86,
        novelty=0.91,
        market_relevance=0.88,
        event_confidence=0.97,
        entity_confidence=0.9,
        source_quality="A",
    )
    assert 0.8 <= s <= 1.0


def test_strip_trade_actions():
    assert "BUY" not in strip_trade_actions("建议 BUY 但不输出")


def test_ollama_failure_fallback(tmp_path):
    n = sample_news("公司预增公告")
    eng = make_engine(tmp_path, FakeNewsClient(fail="raise"))
    out = eng.extract_intelligence(n, symbol="000786.SZ", entity_confidence=0.8)
    assert out["status"] == "error"
    assert out["event_type"] == "unknown"


def test_json_failure_fallback(tmp_path):
    n = sample_news("公司预增公告")
    eng = make_engine(tmp_path, FakeNewsClient(fail="json"))
    out = eng.extract_intelligence(n, symbol="000786.SZ", entity_confidence=0.8)
    assert out["status"] == "error"


def test_token_budget_skips(tmp_path):
    n = sample_news("公司预增公告")
    eng = make_engine(tmp_path, FakeNewsClient(), max_tokens_per_cycle=1)
    out = eng.extract_intelligence(n, symbol="000786.SZ", entity_confidence=0.8)
    assert out.get("status") == "budget" or out.get("fallback_reason") == "token_budget"
