from __future__ import annotations

from pathlib import Path

from ashare.research.gate import apply_research_gate, evaluate_research_gate


def _cfg(tmp_path: Path | None = None) -> dict:
    root = tmp_path or Path(__file__).resolve().parents[1]
    return {"_root": str(root)}


def _candidate(**kwargs) -> dict:
    base = {
        "symbol": "600000.SH",
        "name": "测试",
        "candidate_score": 0.2,
        "leader_score": 0.05,
        "ml_prediction": 0.001,
        "event_score": 0.0,
        "candidate_sources": ["quant"],
        "profit_inflection": {"score": 0.0},
        "news_package": {"net_event_score": 0.0},
        "research_hypotheses": [],
    }
    base.update(kwargs)
    return base


def test_always_pass_top_n():
    cfg = _cfg()
    weak = _candidate(candidate_score=0.01, leader_score=0.0)
    dec = evaluate_research_gate(weak, cfg, rank=0)
    assert dec.passed is True
    assert "always_pass" in dec.reason


def test_weak_signals_rejected_at_low_rank():
    cfg = _cfg()
    weak = _candidate(candidate_score=0.05, leader_score=0.0, ml_prediction=0.0)
    dec = evaluate_research_gate(weak, cfg, rank=5)
    assert dec.passed is False
    assert dec.reason in {"WEAK_SIGNALS", "LOW_CANDIDATE_SCORE", "NO_RESEARCH_TIER"}


def test_news_boost_lower_floor():
    cfg = _cfg()
    news_row = _candidate(
        candidate_score=0.09,
        candidate_sources=["news"],
        news_score=0.2,
        news_package={"net_event_score": 0.2},
    )
    dec = evaluate_research_gate(news_row, cfg, rank=4)
    assert dec.passed is True
    assert dec.boosted is True


def test_gate_research_tier_deep():
    cfg = _cfg()
    row = _candidate(candidate_score=0.3, leader_score=0.4)
    dec = evaluate_research_gate(row, cfg, rank=3)
    assert dec.passed is True
    assert dec.research_tier == "DEEP_RESEARCH"


def test_gate_no_research_tier_rejected():
    cfg = _cfg()
    weak = _candidate(candidate_score=0.05, leader_score=0.0, ml_prediction=0.0)
    dec = evaluate_research_gate(weak, cfg, rank=10)
    assert dec.passed is False
    assert dec.research_tier == "NO_RESEARCH"


def test_apply_gate_batch():
    cfg = _cfg()
    rows = [
        _candidate(symbol="600000.SH", candidate_score=0.3, leader_score=0.4),
        _candidate(symbol="600001.SH", candidate_score=0.05, leader_score=0.0),
        _candidate(symbol="600002.SH", candidate_score=0.15, ml_prediction=0.01),
    ]
    batch = apply_research_gate(rows, cfg)
    assert len(batch.passed) >= 2
    assert batch.summary()["n_in"] == 3
