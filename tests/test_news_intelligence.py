from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ashare.news.classify import classify_news
from ashare.news.common import unix_to_iso
from ashare.news.dedup import dedupe_news
from ashare.news.registry import build_providers
from ashare.news.expectation import expectation_gap
from ashare.news.extract import extract_events
from ashare.news.linking import link_entities
from ashare.news.models import RawNews, make_id, title_hash
from ashare.news.package import filter_asof
from ashare.news.score import net_event_score, source_quality


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
    c = _news("另一条", url="http://x/b", source_id="3")
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


def test_collect_stock_filters_query_weak(monkeypatch):
    from ashare.news.engine import NewsIntelligenceEngine

    good = _news("汉森制药002412发布半年报", source="baidu")
    bad = _news("维峰电子2026年半年报", source="eastmoney")

    class FakeP:
        name = "fake"
        version = "fake_v1"

        def fetch_stock_news(self, symbol, *, name="", limit=20):
            return [good, bad]

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
    n1 = _news("业绩预增")
    n2 = _news("大股东减持")
    e1 = extract_events(n1, symbol="X", relevance=0.9)
    e2 = extract_events(n2, symbol="X", relevance=0.9)
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
    bad = _news("无日期", published_at="not-a-date")
    as_of = datetime(2026, 8, 20, tzinfo=timezone.utc)
    kept = filter_asof([bad], as_of)
    assert kept == []
    kept_all = filter_asof([bad], None)
    assert len(kept_all) == 1


def test_source_quality_a_vs_c():
    a = _news("上交所公告", media="上交所")
    c = _news("市场传闻", media="某论坛")
    assert source_quality(a) == "A"
    assert source_quality(c) in {"C", "D"}
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
    n = _news("时效", published_at=iso)
    from ashare.news.score import freshness_score

    assert freshness_score(n.published_at) >= 0.1
