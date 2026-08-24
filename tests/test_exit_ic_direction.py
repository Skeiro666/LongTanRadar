from __future__ import annotations

"""Mathematical IC direction tests â€?never force production IC to be negative."""

from datetime import date, timedelta

import numpy as np
import pandas as pd

from ashare.portfolio.exit.ic_debug import pearson_ic, spearman_ic
from ashare.portfolio.exit.labels import forward_returns
from ashare.portfolio.exit.heuristic import compute_exit_score
from ashare.portfolio.exit.config import soft_action, load_exit_config


def test_forward_return_is_price_ratio_minus_one():
    dates = [date(2024, 1, 2) + timedelta(days=i) for i in range(30)]
    close = [10.0 + i * 0.1 for i in range(30)]
    bars = pd.DataFrame(
        {"date": dates, "open": close, "high": close, "low": close, "close": close, "volume": [1e6] * 30}
    )
    fr = forward_returns(bars, signal_date=dates[10], horizons=[5], base_mode="signal_close")
    assert fr["base_mode"] == "signal_close"
    assert fr["5"]["available"]
    assert fr["5"]["bar_offset"] == 5
    expected = close[15] / close[10] - 1.0
    assert abs(fr["5"]["return"] - expected) < 1e-12
    assert fr["price_t"] == close[10]
    assert fr["5"]["price"] == close[15]


def test_forward_return_uses_trading_bar_offset_not_calendar():
    # weekends skipped: only business-like sequence in index
    dates = [date(2024, 1, 2) + timedelta(days=i) for i in range(20)]
    close = list(range(20))
    bars = pd.DataFrame(
        {"date": dates, "open": close, "high": close, "low": close, "close": close, "volume": [1.0] * 20}
    )
    fr = forward_returns(bars, signal_date=dates[3], horizons=[5], base_mode="signal_close")
    assert fr["5"]["date"] == str(dates[8])  # index 3+5
    assert fr["signal_date"] == str(dates[3])


def test_case1_high_score_low_return_negative_ic():
    scores = [0.9, 0.8, 0.7, 0.6, 0.5]
    rets = [-0.05, -0.04, -0.03, -0.02, -0.01]
    ic = spearman_ic(scores, rets)
    assert ic is not None and ic < 0


def test_case2_low_score_high_return_negative_ic():
    scores = [0.1, 0.2, 0.3, 0.4, 0.5]
    rets = [0.05, 0.04, 0.03, 0.02, 0.01]
    ic = spearman_ic(scores, rets)
    assert ic is not None and ic < 0


def test_case3_unrelated_near_zero():
    rng = np.random.default_rng(0)
    scores = rng.uniform(0, 1, 80).tolist()
    rets = rng.normal(0, 0.02, 80).tolist()
    ic = spearman_ic(scores, rets)
    assert ic is not None and abs(ic) < 0.35


def test_case4_constructed_monotonic_negative():
    scores = [0.1, 0.2, 0.3, 0.4, 0.5]
    # Economic expectation for exit IC: higher score â†?worse forward return â†?IC < 0
    rets_correct = [0.03, 0.01, -0.01, -0.03, -0.05]
    ic = spearman_ic(scores, rets_correct)
    assert ic is not None and ic < 0
    # Ascending returns with ascending scores â†?positive IC (math identity; not forced flip)
    rets_asc = [-0.05, -0.03, -0.01, 0.01, 0.03]
    assert spearman_ic(scores, rets_asc) is not None and spearman_ic(scores, rets_asc) > 0
    assert pearson_ic(scores, rets_correct) is not None and pearson_ic(scores, rets_correct) < 0


def test_exit_score_higher_means_stronger_exit_pressure():
    cfg = {"_root": "."}
    exit_cfg = load_exit_config(cfg)
    thr = exit_cfg.get("thresholds") or {}
    assert soft_action(0.1, thr) == "HOLD"
    assert soft_action(0.7, thr) == "REDUCE"
    assert soft_action(0.9, thr) == "EXIT"
    # stronger drawdown feature â†?higher score
    low = compute_exit_score(
        {"features": {"drawdown": {"value": 0.1, "available": True}, "volatility": {"value": 0.1, "available": True}}},
        cfg,
    )
    high = compute_exit_score(
        {"features": {"drawdown": {"value": 0.9, "available": True}, "volatility": {"value": 0.9, "available": True}}},
        cfg,
    )
    assert high["exit_score"] > low["exit_score"]


def test_signal_close_ignores_misleading_entry_price_when_base_mode_set():
    dates = [date(2024, 2, 1) + timedelta(days=i) for i in range(20)]
    close = [10.0] * 20
    close[10] = 10.0
    close[15] = 11.0
    bars = pd.DataFrame(
        {"date": dates, "open": close, "high": close, "low": close, "close": close, "volume": [1.0] * 20}
    )
    # wrong entry_price must NOT be used when base_mode=signal_close
    fr = forward_returns(
        bars,
        signal_date=dates[10],
        horizons=[5],
        entry_price=5.0,
        base_mode="signal_close",
    )
    assert abs(fr["5"]["return"] - 0.1) < 1e-12
