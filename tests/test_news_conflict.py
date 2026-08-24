from __future__ import annotations

from ashare.news.conflict import compute_news_conflict


def test_news_positive_quant_weak():
    out = compute_news_conflict(
        intelligence={"direction": "positive"},
        candidate={"leader_score": 0.05, "candidate_score": 0.05},
    )
    assert out["news_conflict"] is True
    assert 0 < out["conflict_score"] <= 1
    assert out["reason"] == "news_positive_quant_weak"


def test_news_negative_price_strong():
    out = compute_news_conflict(
        intelligence={"direction": "negative"},
        candidate={"leader_score": 0.8},
        price_signal="strong",
    )
    assert out["conflict_score"] > 0
    assert out["reason"] == "news_negative_price_strong"


def test_aligned_no_conflict():
    out = compute_news_conflict(
        intelligence={"direction": "positive"},
        candidate={"leader_score": 0.8},
    )
    assert out["conflict_score"] == 0.0
    assert out["news_conflict"] is False
