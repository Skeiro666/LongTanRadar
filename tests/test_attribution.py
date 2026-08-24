from __future__ import annotations

import pandas as pd

from ashare.research.tracking import ReviewEngine, TrackingEngine, _source_bucket


def _panel(sym: str, closes: list[float], start: str = "2024-01-02") -> dict[str, pd.DataFrame]:
    dates = pd.bdate_range(start, periods=len(closes))
    df = pd.DataFrame({"date": dates, "close": closes, "volume": [1e6] * len(closes)})
    return {sym: df}


def test_source_bucket():
    assert _source_bucket(["news"]) == "news_only"
    assert _source_bucket(["quant", "event"]) == "quant_only"
    assert _source_bucket(["news", "quant"]) == "news_plus_quant"
    assert _source_bucket([]) == "unknown"


def test_no_benchmark_means_excess_none():
    sym = "000001.SZ"
    dates = pd.bdate_range("2024-01-02", periods=12)
    panel = _panel(sym, [10 + i * 0.1 for i in range(12)])
    report = {
        "symbol": sym,
        "research_id": "R1",
        "research_time": str(dates[2].date()),
        "candidate_sources": ["news"],
        "decision": {"research_rating": "WATCH"},
    }
    out = TrackingEngine().outcomes_for_report(report, panel)
    assert out["status"] == "ok"
    assert out["source_bucket"] == "news_only"
    cell = out["horizons"]["5"]
    assert "actual_return" in cell
    assert cell["excess_return"] is None
    assert cell["benchmark_return"] is None


def test_attribution_by_source_descriptive_only():
    sym_a, sym_b = "000001.SZ", "600000.SH"
    dates = pd.bdate_range("2024-01-02", periods=15)
    panel = {}
    panel.update(_panel(sym_a, [10.0] * 3 + [11.0] * 12))
    panel.update(_panel(sym_b, [20.0] * 3 + [19.0] * 12, start="2024-01-02"))
    reports = [
        {
            "symbol": sym_a,
            "research_id": "RA",
            "research_time": str(dates[2].date()),
            "candidate_sources": ["news"],
            "decision": {"research_rating": "BUY"},
        },
        {
            "symbol": sym_b,
            "research_id": "RB",
            "research_time": str(dates[2].date()),
            "candidate_sources": ["quant", "event"],
            "decision": {"research_rating": "WATCH"},
        },
    ]
    pack = ReviewEngine({"_root": "."}).attribution_report(reports, panel, horizon="5", persist=False)
    assert pack["available"] is True
    attr = pack["attribution"]
    assert "news_only" in attr["by_source_bucket"]
    assert "quant_only" in attr["by_source_bucket"]
    assert "News â‰?BUY" in " ".join(attr["rules"])
    assert "trading_action" not in pack
    assert "trading_weights" not in attr


def test_ai_incremental_alpha_structure():
    sym_a, sym_b = "000001.SZ", "600000.SH"
    dates = pd.bdate_range("2024-01-02", periods=15)
    panel = {}
    panel.update(_panel(sym_a, [10.0] * 3 + [11.0] * 12))
    panel.update(_panel(sym_b, [20.0] * 3 + [19.0] * 12))
    reports = [
        {
            "symbol": sym_a,
            "research_time": str(dates[2].date()),
            "candidate_sources": ["news"],
            "decision": {"research_rating": "WATCH"},
        },
        {
            "symbol": sym_b,
            "research_time": str(dates[2].date()),
            "candidate_sources": ["quant"],
            "decision": {"research_rating": "GATE_SKIP"},
        },
    ]
    pack = ReviewEngine({"_root": "."}).attribution_report(
        reports, panel, horizon="5", benchmark_returns={"5": 0.0}, persist=False
    )
    alpha = pack.get("ai_incremental_alpha") or {}
    assert alpha.get("method") == "same_universe_topk_ablation" or alpha.get("available") is False
    assert alpha.get("horizon") == "5" or "horizon" not in alpha or pack.get("horizon") == "5"
    legacy = pack.get("ai_incremental_alpha_legacy") or {}
    assert "conclusion" in legacy or legacy.get("note")


def test_with_benchmark_sets_excess():
    sym = "000001.SZ"
    dates = pd.bdate_range("2024-01-02", periods=10)
    panel = _panel(sym, [10.0] * 2 + [11.0] * 8)
    report = {
        "symbol": sym,
        "research_time": str(dates[1].date()),
        "candidate_sources": ["quant"],
        "decision": {"research_rating": "WATCH"},
    }
    out = TrackingEngine().outcomes_for_report(report, panel, benchmark_returns={"5": 0.01})
    cell = out["horizons"]["5"]
    assert cell["benchmark_return"] == 0.01
    assert cell["excess_return"] is not None
