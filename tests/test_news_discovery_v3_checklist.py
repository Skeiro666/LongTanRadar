"""Phase 9 checklist �?News Discovery v3 acceptance tests (no network)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from ashare.candidate import CandidateEngine
from ashare.news.dedup import dedupe_news
from ashare.news.linking import link_entities_open
from ashare.news.models import RawNews, make_id, title_hash
from ashare.news.opportunity import NewsOpportunityEngine
from ashare.news.package import filter_asof
from ashare.research.hypothesis import ResearchHypothesisEngine
from ashare.research.intel_package import build_research_intelligence
from ashare.research.price_reaction import annotate_news_candidate_price
from ashare.research.snapshot import build_snapshot
from ashare.research.tracking import ReviewEngine
from tests.test_platform_engines import _synth_bars


def _n(title: str, **kw) -> RawNews:
    now = datetime.now(timezone.utc).isoformat()
    return RawNews(
        id=kw.get("id") or make_id("N"),
        source=kw.get("source", "sina"),
        title=title,
        fetched_at=now,
        summary=kw.get("summary", title),
        published_at=kw.get("published_at", "2026-08-20 10:00:00"),
        title_hash=title_hash(title),
        url=kw.get("url", ""),
        media=kw.get("media", "新浪财经"),
    )


def test_01_entity_code_and_name_no_false_high_conf():
    n = _n("北新建材000786签订重大合同")
    ents = link_entities_open(n, name_map={"000786.SZ": "北新建材"})
    assert any(e.symbol == "000786.SZ" for e in ents)
    n2 = _n("行业政策利好材料板块")
    assert link_entities_open(n2, name_map={"000786.SZ": "北新建材"}) == []


def test_02_ten_reprints_dedupe_to_one():
    title = "贵州茅台600519公告回购股份"
    items = [_n(title, source=f"src{i}", url=f"https://x.test/{i}") for i in range(10)]
    assert len(dedupe_news(items)) == 1
    eng = NewsOpportunityEngine({"_root": "."})
    out = eng.discover(persist=False, news=items, name_map={}, aliases={"茅台": "600519.SH"})
    assert out["n_news"] == 1 or len(out.get("events") or []) <= 2
    assert len(out["news_candidates"]) <= 2


def test_03_news_candidate_never_emits_buy():
    out = NewsOpportunityEngine({"_root": "."}).discover(
        persist=False,
        news=[_n("000786签订重大合同订单")],
    )
    blob = str(out).upper()
    for c in out["news_candidates"]:
        assert c.get("candidate_source") == "news"
        assert "BUY" not in str(c.get("status", "")).upper()
        assert c.get("trading_action") is None
    assert "\"trading_action\": \"BUY\"" not in blob
    assert "SMALL_POSITION" not in blob


def test_04_05_union_and_candidate_sources(monkeypatch):
    monkeypatch.setattr(
        "ashare.news.engine.NewsIntelligenceEngine.collect_stock",
        lambda self, symbol, **kw: {"net_event_score": 0.0, "news_data_incomplete": False},
    )
    a, b = "600000.SH", "000786.SZ"
    db = _synth_bars(seed=2)
    db["symbol"] = b
    root = Path(__file__).resolve().parents[1]
    eng = CandidateEngine({"_root": str(root), "research": {"funnel": {"max_research_pool": 20}}})
    uni = eng.build_research_universe(
        {a: _synth_bars(), b: db},
        pool={
            "candidates": [
                {
                    "symbol": a,
                    "name": "浦发",
                    "source": "tech_leader",
                    "sources": ["tech_leader"],
                    "event_tags": [],
                    "thesis": "t",
                }
            ],
            "sources": {},
        },
        news_discovery={
            "news_candidates": [
                {
                    "symbol": b,
                    "status": "DISCOVERED",
                    "event_type": "ORDER",
                    "event_impact": 0.7,
                    "confidence": 0.9,
                    "reason": "订单",
                }
            ],
            "rejected": [],
        },
    )
    by = {r["symbol"]: r for r in uni["research_universe"]}
    assert "news" in by[b]["candidate_sources"]
    assert "quant" in by[a]["candidate_sources"]


def test_06_hypothesis_type():
    h = ResearchHypothesisEngine().from_event(
        {"event_type": "ORDER", "direction": "BULLISH", "title": "签大�?, "symbol": "000786.SZ"}
    )
    assert h.to_dict()["type"] == "HYPOTHESIS"


def test_07_08_price_reaction_and_no_auto_action():
    dates = pd.bdate_range("2024-01-02", periods=6)
    df = pd.DataFrame(
        {
            "date": dates,
            "close": [10, 10, 10, 10, 10, 11.5],
            "volume": [1e6] * 6,
            "limit_up": [False] * 6,
            "limit_down": [False] * 6,
        }
    )
    nc = annotate_news_candidate_price(
        {
            "symbol": "000001.SZ",
            "event_direction": "BULLISH",
            "event_time": str(dates[-1].date()),
        },
        {"000001.SZ": df},
    )
    assert nc["price_reaction"]["available"] is True
    assert nc["price_in_risk"] in {"HIGH", "MEDIUM", "LOW"}
    assert "trading_action" not in nc


def test_09_10_asof_and_future_news_dropped():
    as_of = datetime(2026, 8, 20, 23, 59, tzinfo=timezone.utc)
    kept = filter_asof(
        [
            _n("ok", published_at="2026-08-20 09:00:00"),
            _n("future", published_at="2026-08-21 09:00:00"),
            _n("bad_date", published_at="not-a-date"),
        ],
        as_of,
    )
    titles = [x.title for x in kept]
    assert titles == ["ok"]


def test_11_duplicate_url_dedupe():
    a = _n("标题A", url="https://news.example/x")
    b = _n("标题B不同", url="https://news.example/x?utm=1")
    assert len(dedupe_news([a, b])) == 1


def test_12_council_intel_available_false():
    snap = build_snapshot(
        {
            "symbol": "600000.SH",
            "value_available": False,
            "quality_available": False,
            "candidate_sources": ["news"],
            "research_hypotheses": [{"type": "HYPOTHESIS", "evidence_ids": ["N1"]}],
            "news_package": {"news_data_incomplete": True, "expectation": {"available": False}},
        },
        {"_root": str(Path(__file__).resolve().parents[1])},
    )
    pkg = build_research_intelligence(snap)
    assert pkg["data_availability"]["value"]["available"] is False
    assert pkg["data_availability"]["industry_map"]["available"] is False
    assert "News �?BUY" in pkg["rules"]


def test_13_reject_reasons():
    out = NewsOpportunityEngine({"_root": "."}).discover(
        persist=False,
        news=[_n("行业政策利好但无具体股票")],
    )
    assert any(r.get("reject_reason") for r in out["rejected"])


def test_14_outcome_by_source():
    sym = "000001.SZ"
    dates = pd.bdate_range("2024-01-02", periods=12)
    panel = {sym: pd.DataFrame({"date": dates, "close": [10.0] * 3 + [10.5] * 9})}
    pack = ReviewEngine({"_root": "."}).attribution_report(
        [
            {
                "symbol": sym,
                "research_time": str(dates[2].date()),
                "candidate_sources": ["news"],
                "decision": {"research_rating": "WATCH"},
            }
        ],
        panel,
        persist=False,
    )
    assert "news_only" in pack["attribution"]["by_source_bucket"]
