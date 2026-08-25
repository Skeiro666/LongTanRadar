from __future__ import annotations

from ashare.news.conflict import compute_news_quant_conflict


def test_news_positive_quant_weak_high_conflict():
    out = compute_news_quant_conflict(
        intelligence={"direction": "positive"},
        candidate={"leader_score": 0.05, "rs_score": 0.1, "momentum_score": 0.05, "volume_confirm": 0.2},
    )
    assert out["news_conflict"] is True
    assert out["conflict_score"] >= 0.55
    assert out["reason"] == "news_positive_quant_weak"
    assert out["signals"]["rs_weak"] or out["signals"]["momentum_weak"]


def test_news_negative_price_strong():
    out = compute_news_quant_conflict(
        intelligence={"direction": "negative"},
        candidate={
            "leader_score": 0.8,
            "price_reaction": {"available": True, "change_pct": 0.05},
            "price_in_risk": "LOW",
        },
    )
    assert out["conflict_score"] > 0
    assert out["reason"] == "news_negative_price_strong"


def test_aligned_no_conflict():
    out = compute_news_quant_conflict(
        intelligence={"direction": "positive"},
        candidate={"leader_score": 0.8, "rs_score": 0.6, "momentum_score": 0.5, "news_score": 0.2},
    )
    assert out["conflict_score"] == 0.0


def test_news_weak_quant_strong_conflict():
    out = compute_news_quant_conflict(
        intelligence=None,
        candidate={"leader_score": 0.45, "candidate_score": 0.5, "news_score": 0.0},
    )
    assert out["news_conflict"] is True
    assert out["reason"] == "news_weak_quant_strong"
    assert out["conflict_score"] >= 0.65
