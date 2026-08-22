from __future__ import annotations

from pathlib import Path

from ashare.candidate import CandidateEngine
from tests.test_platform_engines import _synth_bars


def _cfg(**funnel):
    root = Path(__file__).resolve().parents[1]
    base = {"max_after_events": 100, "max_union_candidates": 100, "max_research_pool": 20}
    base.update(funnel)
    return {"_root": str(root), "research": {"funnel": base}}


def _pool_row(sym: str, name: str = "浦发银行"):
    return {
        "symbol": sym,
        "name": name,
        "source": "tech_leader",
        "sources": ["tech_leader"],
        "event_tags": ["技术龙头"],
        "thesis": "技术龙头",
    }


def _news_cand(sym: str, **kw):
    return {
        "symbol": sym,
        "status": "DISCOVERED",
        "event_type": "ORDER",
        "event_impact": 0.7,
        "confidence": 0.88,
        "reason": "重大订单",
        "mapping_method": "official_name",
        **kw,
    }


def test_union_news_only_symbol_enters_research(monkeypatch):
    monkeypatch.setattr(
        "ashare.news.engine.NewsIntelligenceEngine.collect_stock",
        lambda self, symbol, **kw: {"net_event_score": 0.1, "news_data_incomplete": False},
    )
    a, b = "600000.SH", "000786.SZ"
    da, db = _synth_bars(seed=1), _synth_bars(seed=2)
    db["symbol"] = b
    panel = {a: da, b: db}
    eng = CandidateEngine(_cfg())
    uni = eng.build_research_universe(
        panel,
        pool={"candidates": [_pool_row(a)], "sources": {}},
        news_discovery={"news_candidates": [_news_cand(b)], "rejected": []},
    )
    by = {r["symbol"]: r for r in uni["research_universe"]}
    assert b in by
    assert "news" in by[b]["candidate_sources"]
    assert "quant" in by[a]["candidate_sources"]
    assert by[b].get("in_council") is True


def test_union_tags_news_on_existing_quant_name(monkeypatch):
    monkeypatch.setattr(
        "ashare.news.engine.NewsIntelligenceEngine.collect_stock",
        lambda self, symbol, **kw: {"net_event_score": 0.0, "news_data_incomplete": False},
    )
    a = "600000.SH"
    panel = {a: _synth_bars()}
    eng = CandidateEngine(_cfg())
    uni = eng.build_research_universe(
        panel,
        pool={"candidates": [_pool_row(a)], "sources": {}},
        news_discovery={"news_candidates": [_news_cand(a)], "rejected": []},
    )
    row = uni["research_universe"][0]
    assert set(row["candidate_sources"]) >= {"quant", "news"}


def test_union_missing_bars_rejected(monkeypatch):
    monkeypatch.setattr(
        "ashare.news.engine.NewsIntelligenceEngine.collect_stock",
        lambda self, symbol, **kw: {"net_event_score": 0.0, "news_data_incomplete": False},
    )
    a = "600000.SH"
    eng = CandidateEngine(_cfg())
    uni = eng.build_research_universe(
        {a: _synth_bars()},
        pool={"candidates": [_pool_row(a)], "sources": {}},
        news_discovery={"news_candidates": [_news_cand("000001.SZ")], "rejected": []},
    )
    assert any(r.get("reject_reason") == "FACTOR_VALIDATION_FAIL" for r in uni["rejected"])
    assert all(r["symbol"] != "000001.SZ" for r in uni["research_universe"])


def test_union_ranking_cutoff(monkeypatch):
    monkeypatch.setattr(
        "ashare.news.engine.NewsIntelligenceEngine.collect_stock",
        lambda self, symbol, **kw: {"net_event_score": 0.0, "news_data_incomplete": False},
    )
    a, b = "600000.SH", "000786.SZ"
    db = _synth_bars(seed=3)
    db["symbol"] = b
    eng = CandidateEngine(_cfg(max_research_pool=1))
    uni = eng.build_research_universe(
        {a: _synth_bars(), b: db},
        pool={"candidates": [_pool_row(a), _pool_row(b, "北新建材")], "sources": {}},
        news_discovery={"news_candidates": [], "rejected": []},
    )
    assert len(uni["research_universe"]) == 1
    assert any(r.get("reject_reason") == "RANKING_CUTOFF" for r in uni["rejected"])
