"""Leakage tests for unified EntryEvent features vs labels."""
from __future__ import annotations

import numpy as np
import pandas as pd

from ashare.leader.entry_event_dataset import build_events_for_symbol, make_event_id
from ashare.leader.entry_distribution import round_trip_cost_buy_sell
from ashare.leader.chase_risk import ChaseRiskEngine
from ashare.leader.reentry_engine import ReentryEngine
from ashare.leader.stage_engine import StageEngine


def _bars(n: int = 140, seed: int = 3) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2023-01-03", periods=n)
    close = 10 + np.cumsum(rng.normal(0, 0.2, size=n))
    close = np.maximum(close, 1.0)
    lu = np.zeros(n, dtype=bool)
    for k in range(4):
        i = n - 30 + k
        lu[i] = True
        close[i] = close[i - 1] * 1.1
    # pullback then bounce
    close[n - 26] = close[n - 27] * 0.97
    close[n - 25] = close[n - 26] * 0.98
    close[n - 24] = close[n - 25] * 1.03
    high = close * 1.01
    low = close * 0.99
    open_ = close * 0.995
    return pd.DataFrame(
        {
            "date": dates,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": rng.integers(1e6, 3e6, size=n).astype(float),
            "amount": close * 1e6,
            "limit_up": lu,
            "limit_down": np.zeros(n, dtype=bool),
        }
    )


def test_one_event_per_symbol_date():
    df = _bars()
    cost = round_trip_cost_buy_sell({})
    evs = build_events_for_symbol(
        df,
        "TEST.SZ",
        cost_rate=cost,
        stage_e=StageEngine(),
        chase_e=ChaseRiskEngine(),
        re_e=ReentryEngine(),
    )
    keys = [(e.symbol, e.date) for e in evs]
    assert len(keys) == len(set(keys))


def test_features_stable_under_future_spike():
    df = _bars()
    cost = round_trip_cost_buy_sell({})
    a = build_events_for_symbol(
        df, "TEST.SZ", cost_rate=cost, stage_e=StageEngine(), chase_e=ChaseRiskEngine(), re_e=ReentryEngine()
    )
    spiked = df.copy()
    spiked.loc[spiked.index[-8]:, ["close", "high", "open", "low"]] *= 4.0
    b = build_events_for_symbol(
        spiked, "TEST.SZ", cost_rate=cost, stage_e=StageEngine(), chase_e=ChaseRiskEngine(), re_e=ReentryEngine()
    )
    # Compare events on dates that exist in both and are before spike window
    a_map = {e.date: e for e in a}
    b_map = {e.date: e for e in b}
    common = sorted(set(a_map) & set(b_map))
    assert common
    # take earliest common event (before mutated tail)
    d0 = common[0]
    assert a_map[d0].entry_mode == b_map[d0].entry_mode
    assert a_map[d0].pullback_depth == b_map[d0].pullback_depth
    assert a_map[d0].health == b_map[d0].health
    assert a_map[d0].stage == b_map[d0].stage


def test_labels_are_primary_t1_open_net():
    df = _bars()
    cost = round_trip_cost_buy_sell({})
    evs = build_events_for_symbol(
        df, "TEST.SZ", cost_rate=cost, stage_e=StageEngine(), chase_e=ChaseRiskEngine(), re_e=ReentryEngine()
    )
    assert evs
    lab = evs[0].labels
    assert lab.get("primary_execution") == "T+1_open_net"
    assert "t+5_net" in lab
    assert "t+5_cc" in lab  # secondary
    # net = gross - cost
    if lab.get("t+5_gross") is not None and lab.get("t+5_net") is not None:
        assert abs(lab["t+5_net"] - (lab["t+5_gross"] - cost)) < 1e-9


def test_health_not_derived_from_future_return():
    """Health classification must not use label fields."""
    from ashare.leader.entry_distribution import classify_pullback_health

    row = {
        "structure_break": 0.0,
        "volume_contraction": 0.2,
        "big_red_volume": 0.0,
        "high_open_low_close": 0.0,
        "consecutive_down_days": 1,
        "volume_ratio_to_peak": 0.4,
        "pullback_from_high": -0.04,
        # poison future labels — must be ignored
        "t+5": 0.99,
        "labels": {"t+5_net": 0.99},
    }
    assert classify_pullback_health(row) == "HEALTHY_PULLBACK"


def test_event_id_stable():
    assert make_event_id("000001.SZ", "2024-01-02", "PULLBACK") == make_event_id(
        "000001.SZ", "2024-01-02", "PULLBACK"
    )
