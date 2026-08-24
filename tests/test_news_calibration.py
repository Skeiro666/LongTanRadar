from __future__ import annotations

from ashare.research.news_calibration import build_news_calibration, calibrate_buckets


def _outcome(score: float, ret: float) -> dict:
    return {
        "news_intelligence_score": score,
        "news_intelligence": {"importance": score, "novelty": score},
        "primary_horizons": {
            "5": {"selection_alpha": ret},
            "10": {"selection_alpha": ret * 0.8},
        },
    }


def test_calibration_buckets_insufficient():
    out = calibrate_buckets([], "news_intelligence_score", min_n=5)
    assert out["buckets"]
    for b in out["buckets"]:
        assert b["horizons"]["5"]["status"] == "INSUFFICIENT_SAMPLE"


def test_calibration_with_samples():
    outcomes = [_outcome(0.1 + i * 0.15, 0.01 * i) for i in range(6)]
    pack = build_news_calibration(outcomes, {"research": {"attribution": {"minimum_sample_size": 30}, "news_calibration": {"minimum_sample": 2}}})
    assert "score" in pack
    assert "quadrants" in pack
