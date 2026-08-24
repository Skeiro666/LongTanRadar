from __future__ import annotations

from ashare.portfolio.exit.thesis_decay import evaluate_thesis_decay


def test_thesis_decay_high_on_event_completion_and_news_flip():
    out = evaluate_thesis_decay(
        buy_thesis={"profit_state": "ACTIVE", "event_state": "ACTIVE", "news_direction": "positive", "momentum": 0.2, "leader_score": 0.5},
        current={"profit_state": "WEAKENING", "event_state": "COMPLETED", "news_direction": "negative", "momentum": -0.1, "leader_score": 0.1},
    )
    assert out["available"]
    assert out["thesis_decay"] is not None
    assert out["level"] in {"HIGH", "MEDIUM"}


def test_thesis_decay_unavailable():
    out = evaluate_thesis_decay(buy_thesis={}, current={})
    assert out["available"] is False
    assert out["level"] == "UNKNOWN"
