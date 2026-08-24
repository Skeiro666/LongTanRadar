from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from ashare.portfolio.exit.backtest import run_exit_backtest
from ashare.portfolio.exit.alpha import build_exit_alpha
from ashare.portfolio.exit.calibration import calibrate_exit_scores
from ashare.portfolio.exit.validation import feature_ic_table, feature_redundancy
from ashare.portfolio.exit.execution import t1_open_fill


def _bars(n=120, seed=3):
    rng = np.random.default_rng(seed)
    dates = [date(2023, 6, 1) + timedelta(days=i) for i in range(n)]
    close = 10 * np.cumprod(1 + rng.normal(0, 0.015, n))
    return pd.DataFrame(
        {
            "date": dates,
            "open": close * 0.999,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": rng.integers(1e5, 1e6, n).astype(float),
        }
    )


def test_exit_backtest_structure():
    b = _bars()
    bars = {"AAA.SH": b}
    entries = [
        {"symbol": "AAA.SH", "entry_date": str(b["date"].iloc[20 + i * 3]), "entry_price": 10.0}
        for i in range(6)
    ]
    bt = run_exit_backtest(
        bars,
        entries,
        cfg={"_root": ".", "exit": {"backtest": {"scan_step": 3}}},
        minimum_sample=3,
    )
    for key in ("no_exit", "fixed_stop", "exit_engine", "exit_wo_trend", "exit_wo_news"):
        assert key in bt["strategies"]
        assert "sample_count" in bt["strategies"][key]
    assert bt["execution_model"] == "t1_open"


def test_exit_alpha_ablation_rows():
    b = _bars(seed=9)
    bars = {"AAA.SH": b}
    entries = [
        {"symbol": "AAA.SH", "entry_date": str(b["date"].iloc[25 + i * 4]), "entry_price": 10.0}
        for i in range(5)
    ]
    alpha = build_exit_alpha(
        bars,
        entries,
        cfg={"exit": {"minimum_sample": 3, "backtest": {"scan_step": 3}}, "_root": "."},
    )
    assert len(alpha["strategies"]) >= 5


def test_backtest_uses_t1_open_model():
    b = _bars(n=100)
    bars = {"AAA.SH": b}
    entries = [
        {"symbol": "AAA.SH", "entry_date": str(b["date"].iloc[20 + i * 5]), "entry_price": 10.0}
        for i in range(4)
    ]
    bt = run_exit_backtest(
        bars,
        entries,
        cfg={"_root": ".", "exit": {"minimum_sample": 2, "backtest": {"scan_step": 3}}},
        minimum_sample=2,
    )
    assert bt["execution_model"] == "t1_open"
    assert "exit_engine" in bt["strategies"]
    assert "exit_wo_news" in bt["strategies"]
    eng = bt["strategies"]["exit_engine"]
    assert "gross" in eng and "net" in eng


def test_exit_calibration_full():
    b = _bars()
    bars = {"AAA.SH": b}
    rows = [
        {"symbol": "AAA.SH", "signal_date": str(b["date"].iloc[50 + i]), "exit_score": s}
        for i, s in enumerate([0.1, 0.3, 0.5, 0.7, 0.9] * 8)
    ]
    cal = calibrate_exit_scores(rows, bars, cfg={"exit": {"minimum_sample": 5, "validation": {"minimum_sample": 5, "bucket_minimum_sample": 3}}, "_root": "."})
    assert len(cal["buckets"]) == 5
    assert "ic" in cal
    assert "monotonicity" in cal


def test_feature_ic_and_redundancy_insufficient_without_features():
    b = _bars()
    rows = [{"symbol": "AAA.SH", "signal_date": str(b["date"].iloc[60]), "exit_score": 0.5}]
    ic = feature_ic_table(rows, {"AAA.SH": b}, cfg={"exit": {"validation": {"minimum_sample": 30}}, "_root": "."})
    assert ic["status"] == "INSUFFICIENT_SAMPLE"
    red = feature_redundancy(rows, cfg={"_root": "."})
    assert red["status"] == "INSUFFICIENT_SAMPLE"


def test_t1_fill_helper():
    b = _bars()
    f = t1_open_fill(b, 10)
    assert f["available"]
    assert f["fill_price"] == float(b.iloc[11]["open"])
