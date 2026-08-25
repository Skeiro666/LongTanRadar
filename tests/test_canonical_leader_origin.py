"""Canonical leader origin and board_count repair — no BUY wiring."""
from __future__ import annotations

import numpy as np

from ashare.leader.canonical_edge_lab import (
    is_canonical_leader_event,
    last_limit_up_origin,
    research_sample_tier,
)
from ashare.leader.entry_validation import _consecutive_limit_up_series


def test_today_board_zero_on_pullback_but_peak_kept():
    lu = np.array([False] * 8 + [True, True, True, False, False])
    boards = _consecutive_limit_up_series(lu)
    i = len(lu) - 1
    origin = last_limit_up_origin(lu, boards, i)
    assert origin["today_board"] == 0
    assert origin["leader_board_count"] == 3
    assert origin["days_since_limit_up"] == 2
    assert origin["leader_valid"] is True
    assert is_canonical_leader_event(origin, entry_mode="PULLBACK", limit_up=False) is True


def test_board_zero_without_streak_is_not_leader():
    lu = np.array([False] * 12)
    boards = _consecutive_limit_up_series(lu)
    origin = last_limit_up_origin(lu, boards, 10)
    assert origin["leader_board_count"] == 0
    assert origin["leader_valid"] is False
    assert is_canonical_leader_event(origin, entry_mode="PULLBACK", limit_up=False) is False


def test_single_limit_up_not_canonical_pullback():
    lu = np.array([False] * 9 + [True, False])
    boards = _consecutive_limit_up_series(lu)
    origin = last_limit_up_origin(lu, boards, 10)
    assert origin["leader_board_count"] == 1
    assert is_canonical_leader_event(origin, entry_mode="PULLBACK", limit_up=False) is False


def test_direct_chase_requires_three_boards_today():
    lu = np.array([True, True, True])
    boards = _consecutive_limit_up_series(lu)
    origin = last_limit_up_origin(lu, boards, 2)
    assert origin["today_board"] == 3
    assert is_canonical_leader_event(origin, entry_mode="DIRECT_CHASE", limit_up=True) is True
    origin2 = last_limit_up_origin(lu, boards, 1)
    assert origin2["today_board"] == 2
    assert is_canonical_leader_event(origin2, entry_mode="DIRECT_CHASE", limit_up=True) is False


def test_sample_tiers():
    assert research_sample_tier(20) == "INSUFFICIENT_SAMPLE"
    assert research_sample_tier(50) == "LOW_SAMPLE"
    assert research_sample_tier(150) == "OK"
    assert research_sample_tier(400) == "STRONG"


def test_origin_uses_only_past_bars():
    lu = np.zeros(20, dtype=bool)
    lu[8:11] = True
    lu[18:20] = True
    boards = _consecutive_limit_up_series(lu)
    origin = last_limit_up_origin(lu, boards, 12)
    assert origin["leader_board_count"] == 3
    assert origin["days_since_limit_up"] == 2
