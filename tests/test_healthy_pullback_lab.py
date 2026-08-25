"""Tests for healthy pullback lab (no future in health flags)."""
from __future__ import annotations

from ashare.leader.healthy_pullback_lab import health_flags, is_healthy_with_ablation, is_pullback_day


def test_health_flags_asof():
    flags = health_flags(
        {
            "structure_break": 0.0,
            "volume_contraction": 0.2,
            "big_red_volume": 0.0,
            "high_open_low_close": 0.0,
            "consecutive_down_days": 1,
            "volume_ratio_to_peak": 0.4,
            "pullback_from_high": -0.04,
        }
    )
    assert is_healthy_with_ablation(flags)
    assert not is_healthy_with_ablation({**flags, "no_structure_break": False})


def test_ablation_drop_volume_still_requires_others():
    flags = health_flags(
        {
            "structure_break": 0.0,
            "volume_contraction": 0.0,  # fails volume
            "big_red_volume": 0.0,
            "high_open_low_close": 0.0,
            "consecutive_down_days": 1,
            "volume_ratio_to_peak": 0.4,
            "pullback_from_high": -0.04,
        }
    )
    assert not is_healthy_with_ablation(flags)
    assert is_healthy_with_ablation(flags, drop="volume_contraction")


def test_is_pullback_day_rejects_limit_up():
    assert not is_pullback_day({"pullback_from_high": -0.05, "volume_contraction": 0.2}, days_since_lu=2, limit_up=True)
    assert is_pullback_day({"pullback_from_high": -0.05, "volume_contraction": 0.2, "structure_break": 0}, days_since_lu=2, limit_up=False)
