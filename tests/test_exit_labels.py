from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from ashare.portfolio.exit.labels import forward_returns


def test_labels_only_read_future_for_targets():
    dates = [date(2024, 1, 1) + timedelta(days=i) for i in range(30)]
    close = [10 + i * 0.1 for i in range(30)]
    bars = pd.DataFrame({"date": dates, "close": close, "high": close, "low": close, "open": close, "volume": [1] * 30})
    fr = forward_returns(bars, signal_date=dates[10], horizons=[1, 5, 10, 19])
    assert fr["1"]["available"]
    assert abs(fr["5"]["return"] - (close[15] / close[10] - 1)) < 1e-9
    assert fr["19"]["available"]
