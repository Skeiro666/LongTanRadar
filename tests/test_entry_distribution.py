"""Smoke tests for entry distribution lab (no LLM, no future in features)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from ashare.leader.entry_distribution import (
    classify_pullback_health,
    distribution_stats,
    enrich_sample_from_bars,
    expected_value_pack,
    good_entry_gate,
    round_trip_cost_buy_sell,
)


def test_distribution_stats_and_ev():
    rng = np.random.default_rng(0)
    rets = list(rng.normal(0.01, 0.08, size=40))
    dist = distribution_stats(rets)
    assert dist["status"] == "OK"
    assert "p10" in dist and "histogram" in dist
    ev = expected_value_pack(rets, cost_rate=0.002)
    assert ev["ev"] is not None
    assert ev["expected_return_after_cost"] < ev["gross_mean"]


def test_cost_rate_positive():
    assert round_trip_cost_buy_sell({"costs": {}}) > 0


def test_pullback_health_asof_only():
    healthy = classify_pullback_health(
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
    dangerous = classify_pullback_health(
        {"structure_break": 1.0, "volume_contraction": 0.0, "big_red_volume": 1.0, "consecutive_down_days": 4}
    )
    assert healthy == "HEALTHY_PULLBACK"
    assert dangerous == "DANGEROUS_PULLBACK"


def test_enrich_does_not_change_with_future_spike():
    n = 100
    dates = pd.bdate_range("2024-01-02", periods=n)
    close = np.linspace(10, 20, n)
    df = pd.DataFrame(
        {
            "date": dates,
            "open": close * 0.99,
            "high": close * 1.02,
            "low": close * 0.98,
            "close": close,
            "volume": np.full(n, 1e6),
            "amount": close * 1e6,
            "limit_up": [False] * n,
            "limit_down": [False] * n,
        }
    )
    i = 70
    row = {
        "date": str(dates[i].date()),
        "symbol": "TEST.SZ",
        "board_count": 3,
        "structure_score": 0.5,
        "pullback_score": 0.5,
        "volume_score": 0.5,
        "entry_mode": "PULLBACK",
        "labels": {"t+5": 0.01},
    }
    a = enrich_sample_from_bars(row, df, cost_rate=0.002)
    spiked = df.copy()
    spiked.loc[spiked.index[i + 1] :, ["close", "high", "open"]] *= 3
    b = enrich_sample_from_bars(row, spiked, cost_rate=0.002)
    assert a.get("pullback_from_high") == b.get("pullback_from_high")
    assert a.get("entry_quality") == b.get("entry_quality")
    # labels after as-of may differ (future) — that's expected for T+ returns
    assert a.get("reentry_score_status") == "REENTRY_SCORE_UNCALIBRATED"


def test_good_entry_gate_strict():
    bad = good_entry_gate(
        {
            "status": "OK",
            "mean_return": 0.03,
            "win_rate": 0.5,
            "limit_down_rate": 0.49,
            "MAE_mean": -0.15,
            "MDD": -0.1,
            "risk_adjusted_return": -0.1,
        }
    )
    assert bad["verdict"] == "NO_EDGE_PROVEN"
