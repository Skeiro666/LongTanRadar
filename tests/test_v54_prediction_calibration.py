"""V5.4 prediction calibration."""

from __future__ import annotations

from ashare.research.calibration import build_calibration


def test_v54_calibration_respects_minimum_sample():
    reports = [{"symbol": f"S{i}", "chairman": {"confidence": 0.75}} for i in range(6)]
    outcomes = [
        {"symbol": f"S{i}", "primary_horizons": {"5": {"actual_return": 0.01, "selection_alpha": 0.005}}}
        for i in range(6)
    ]
    cal = build_calibration(reports, outcomes, {"research": {"attribution": {"minimum_sample_size": 30}}})
    assert cal.get("confidence_sample_count", 0) == 6
    bucket = list((cal.get("confidence_calibration") or {}).values())
    assert bucket and bucket[0].get("insufficient_sample") is True
