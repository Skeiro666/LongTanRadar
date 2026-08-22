"""V5.4 Prediction calibration tests."""

from __future__ import annotations

from ashare.research.calibration import build_calibration


def test_eer_calibration_bias():
    reports = []
    outcomes = []
    for i in range(6):
        sym = f"60000{i}.SH"
        reports.append(
            {
                "symbol": sym,
                "chairman": {"confidence": 0.75},
                "research_hypotheses": [
                    {"investment_hypothesis": {"expected_excess_return": {"available": True, "value": 0.08}}}
                ],
            }
        )
        outcomes.append(
            {"symbol": sym, "primary_horizons": {"5": {"selection_alpha": 0.02, "actual_return": 0.02}}}
        )
    cfg = {"research": {"attribution": {"minimum_sample": 5, "horizons_days": [5, 10]}}}
    cal = build_calibration(reports, outcomes, cfg)
    assert cal["available"] is True
    assert cal["eer_sample_count"] == 6
    bucket = cal["eer_calibration"].get("5_10pct") or cal["eer_calibration"].get("10pct_plus")
    assert bucket is not None


def test_no_fake_eer_when_unavailable():
    reports = [{"symbol": "600000.SH", "chairman": {"confidence": 0.6}, "research_hypotheses": []}]
    outcomes = [{"symbol": "600000.SH", "primary_horizons": {"5": {"actual_return": 0.01}}}]
    cal = build_calibration(reports, outcomes, {"research": {"attribution": {"minimum_sample": 5}}})
    assert cal["eer_sample_count"] == 0
