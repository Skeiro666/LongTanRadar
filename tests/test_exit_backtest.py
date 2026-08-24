from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from ashare.portfolio.exit.backtest import run_exit_backtest
from ashare.portfolio.exit.alpha import build_exit_alpha
from ashare.portfolio.exit.calibration import calibrate_exit_scores


def _bars(n=120, seed=3):
    rng = np.random.default_rng(seed)
    dates = [date(2023, 6, 1) + timedelta(days=i) for i in range(n)]
    close = 10 * np.cumprod(1 + rng.normal(0, 0.015, n))
    return pd.DataFrame(
        {
            "date": dates,
            "open": close,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": rng.integers(1e5, 1e6, n).astype(float),
        }
    )


def test_exit_backtest_structure():
    bars = {"AAA.SH": _bars()}
    entries = [{"symbol": "AAA.SH", "entry_date": "2023-06-20", "entry_price": 10.0} for _ in range(40)]
    bt = run_exit_backtest(bars, entries, cfg={"_root": "."}, minimum_sample=10)
    for key in ("no_exit", "fixed_stop", "exit_engine"):
        assert key in bt["strategies"]
        assert "sample_count" in bt["strategies"][key]


def test_exit_alpha_deltas():
    bars = {"AAA.SH": _bars(seed=9)}
    entries = [{"symbol": "AAA.SH", "entry_date": "2023-06-25", "entry_price": 10.0} for _ in range(35)]
    alpha = build_exit_alpha(bars, entries, cfg={"exit": {"minimum_sample": 10}, "_root": "."})
    assert len(alpha["strategies"]) == 3


def test_exit_calibration():
    b = _bars()
    bars = {"AAA.SH": b}
    rows = [
        {"symbol": "AAA.SH", "signal_date": str(b["date"].iloc[50 + i]), "exit_score": s}
        for i, s in enumerate([0.1, 0.3, 0.5, 0.7, 0.9] * 8)
    ]
    cal = calibrate_exit_scores(rows, bars, cfg={"exit": {"minimum_sample": 5}, "_root": "."})
    assert len(cal["buckets"]) == 5
