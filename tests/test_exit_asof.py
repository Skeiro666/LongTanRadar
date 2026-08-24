from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from ashare.portfolio.exit.features import compute_exit_features
from ashare.portfolio.exit.labels import assert_features_asof


def test_features_never_use_future_bars():
    dates = [date(2024, 3, 1) + timedelta(days=i) for i in range(40)]
    close = list(range(40))
    bars = pd.DataFrame(
        {
            "date": dates,
            "open": close,
            "high": [c + 1 for c in close],
            "low": [c - 1 for c in close],
            "close": close,
            "volume": [1e6] * 40,
        }
    )
    as_of = dates[20]
    pack = compute_exit_features(bars=bars, as_of=as_of, position={"entry_price": 5.0, "entry_date": "2024-03-05"})
    assert assert_features_asof(pack, bars, as_of)
    assert float(pack["current_price"]) == 20.0
