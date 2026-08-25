"""Regression: tz-aware as_of must not break daily-bar filters."""
from __future__ import annotations

from datetime import date, datetime, timezone

import pandas as pd

from ashare.asof import asof_cutoff, mask_on_or_before
from ashare.services.research import _panel_asof


def _bars() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-08-20", "2026-08-25", "2026-08-26"]),
            "symbol": ["000001.SZ"] * 3,
            "open": [10.0, 11.0, 12.0],
            "high": [10.5, 11.5, 12.5],
            "low": [9.5, 10.5, 11.5],
            "close": [10.0, 11.0, 12.0],
            "volume": [1e6, 1e6, 1e6],
            "amount": [1e7, 1e7, 1e7],
            "pct_chg": [0.0, 0.1, 0.09],
            "is_st": [False, False, False],
            "is_halt": [False, False, False],
            "limit_up": [False, False, False],
            "limit_down": [False, False, False],
        }
    )


def test_asof_cutoff_strips_tz():
    cut = asof_cutoff("2026-08-25T23:59:59+00:00")
    assert cut is not None
    assert cut.tz is None
    assert cut == pd.Timestamp("2026-08-25")


def test_mask_on_or_before_tz_aware():
    df = _bars()
    m = mask_on_or_before(df["date"], datetime(2026, 8, 25, 23, 59, 59, tzinfo=timezone.utc))
    assert int(m.sum()) == 2
    assert list(df.loc[m, "date"].dt.strftime("%Y-%m-%d")) == ["2026-08-20", "2026-08-25"]


def test_panel_asof_accepts_tz_aware_datetime():
    panel = {"000001.SZ": _bars()}
    snap = _panel_asof(panel, datetime(2026, 8, 25, 23, 59, 59, tzinfo=timezone.utc))
    assert "000001.SZ" in snap["bars"]
    assert snap["bars"]["000001.SZ"].close == 11.0
    assert len(snap["hist"]["000001.SZ"]) == 2


def test_panel_asof_accepts_date():
    panel = {"000001.SZ": _bars()}
    snap = _panel_asof(panel, date(2026, 8, 25))
    assert len(snap["hist"]["000001.SZ"]) == 2
