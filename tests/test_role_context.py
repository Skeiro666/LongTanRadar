from __future__ import annotations

import json
from pathlib import Path

from ashare.research.intel_package import (
    build_chairman_context,
    build_research_intelligence,
    build_role_context,
    slim_roundtable_candidate,
)


def _sample_snapshot() -> dict:
    return {
        "symbol": "000786.SZ",
        "name": "北新建材",
        "value_available": False,
        "quality_available": False,
        "candidate_sources": ["news", "quant"],
        "research_hypotheses": [
            {
                "type": "HYPOTHESIS",
                "layers": {"FACT": "订单", "INFERENCE": "增收", "HYPOTHESIS": "利润改善"},
                "evidence_ids": ["N1"],
            }
        ],
        "news_package": {
            "news_data_incomplete": False,
            "news_ids": ["N1"],
            "event_ids": ["E1"],
            "expectation": {"available": False},
            "counts": {"last_7d": 3},
            "net_event_score": 0.5,
            "timeline": [{"title": "订单新闻", "date": "2026-08-20", "event_type": "order"}],
            "last_7d": [
                {"title": "长标题" * 20, "date": "2026-08-20", "body": "正文" * 100},
                {"title": "第二条", "date": "2026-08-19"},
            ],
            "conflicts": [{"type": "price_in", "note": "已反应"}],
        },
        "news_discovery": {"price_in_risk": "HIGH", "events": [{"symbol": "000786.SZ", "event_type": "order"}]},
        "quant": {
            "leader_score": 0.4,
            "ml_prediction": 0.02,
            "factors": {"momentum_20d": 0.1, "vol_confirm": 0.2},
        },
        "profit_inflection": {"available": True, "score": 0.6, "yoy_pct": 80},
        "event": {"score": 0.3},
        "market_regime": "RISK_ON",
        "market": {"price": 10},
        "trigger": {"type": "news"},
    }


def _cfg() -> dict:
    return {"_root": str(Path(__file__).resolve().parents[1])}


def test_quant_role_drops_news_bodies():
    snap = _sample_snapshot()
    full = build_research_intelligence(snap, role_id="quant")
    slim = build_role_context(snap, "quant", cfg=_cfg())
    assert full.get("news_context", {}).get("last_7d")
    assert "last_7d" not in (slim.get("news_context") or {})
    assert slim["quant_context"]["factors"]
    assert slim["evidence_ids"]


def test_event_role_drops_factor_grid():
    snap = _sample_snapshot()
    slim = build_role_context(snap, "event", cfg=_cfg())
    assert "factor_context" not in slim
    assert slim["research_hypotheses"]
    last_7d = slim["news_context"]["last_7d"]
    assert last_7d and "body" not in last_7d[0]


def test_chairman_context_slimmer_than_full():
    snap = _sample_snapshot()
    opinions = {
        "quant": {"role": "quant", "score": 0.3, "stance": "bull", "points": ["a"], "status": "ok"},
        "bear": {"role": "bear", "score": -0.1, "stance": "neutral", "status": "ok"},
    }
    payload = build_chairman_context(snap, opinions, [], cfg=_cfg())
    assert "snapshot_quant" not in payload
    assert "quant_summary" in payload["research_intelligence"]
    assert "model" not in payload["opinions"]["quant"]
    full_len = len(json.dumps(build_research_intelligence(snap), ensure_ascii=False))
    slim_len = len(json.dumps(payload, ensure_ascii=False))
    assert slim_len < full_len


def test_valuation_role_context_minimal():
    snap = _sample_snapshot()
    slim = build_role_context(snap, "valuation", cfg=_cfg())
    assert "news_context" not in slim
    assert slim["data_availability"]["value"]["available"] is False
    assert slim["evidence_ids"]


def test_slim_roundtable_candidate_by_role():
    cand = {
        "symbol": "600000.SH",
        "name": "浦发",
        "quant": {"score": 0.5, "factors_z": {"a": 1}, "why": "x", "close": 10},
        "board_count": 2,
        "kline": {"last_close": 10, "ret_1d_pct": 1.0, "recent_bars": [{"c": 10}]},
        "news_package": {"timeline": [{"title": "t"}], "legacy_headlines": [{"title": "h"}]},
        "news": [{"title": "h", "body": "long" * 50}],
        "profit_gap_score": 1.2,
    }
    dragon = slim_roundtable_candidate(cand, "dragon", cfg=_cfg())
    event = slim_roundtable_candidate(cand, "event", cfg=_cfg())
    assert "kline" in dragon
    assert "profit_gap_score" not in dragon
    assert "kline" not in event
    assert event.get("profit_gap_score") == 1.2
