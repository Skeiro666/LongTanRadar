"""V5.4 prediction calibration."""

from tests.test_v5_4_calibration import test_eer_calibration_buckets  # noqa: F401


def test_v54_calibration_minimum_sample():
    from ashare.research.calibration import build_calibration

    reports = [{"symbol": f"S{i}", "chairman": {"confidence": 0.75}} for i in range(6)]
    outcomes = [
        {"symbol": f"S{i}", "primary_horizons": {"5": {"actual_return": 0.01, "selection_alpha": 0.005}}}
        for i in range(6)
    ]
    cal = build_calibration(reports, outcomes, {"research": {"attribution": {"minimum_sample_size": 30}}})
    assert cal.get("confidence_sample_count", 0) == 6
