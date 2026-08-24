from __future__ import annotations

"""Exit score calibration buckets."""

from typing import Any

import pandas as pd

from ashare.portfolio.exit.config import load_exit_config
from ashare.portfolio.exit.labels import forward_returns


_BUCKETS = [(0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.01)]


def calibrate_exit_scores(
    rows: list[dict[str, Any]],
    bars_by_symbol: dict,
    *,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    rows: [{symbol, signal_date, exit_score, exit_price?}]
    """
    exit_cfg = load_exit_config(cfg)
    min_n = int(exit_cfg.get("minimum_sample") or 30)
    # use smaller floor for bucket display but mark insufficient
    bucket_min = max(5, min_n // 3)
    out_buckets = []
    means = []
    for lo, hi in _BUCKETS:
        rets5, rets10 = [], []
        for r in rows:
            s = r.get("exit_score")
            if s is None:
                continue
            s = float(s)
            if not (lo <= s < hi):
                continue
            bars = bars_by_symbol.get(str(r.get("symbol")))
            if bars is None:
                continue
            fr = forward_returns(
                bars,
                signal_date=r.get("signal_date"),
                horizons=[5, 10],
                entry_price=r.get("exit_price"),
            )
            if (fr.get("5") or {}).get("available"):
                rets5.append(float(fr["5"]["return"]))
            if (fr.get("10") or {}).get("available"):
                rets10.append(float(fr["10"]["return"]))
        n = max(len(rets5), len(rets10))
        if n < bucket_min:
            cell = {
                "range": f"{lo:.1f}-{hi:.1f}",
                "sample_count": n,
                "status": "INSUFFICIENT_SAMPLE",
                "t5_mean": None,
                "t10_mean": None,
            }
        else:
            m5 = float(pd.Series(rets5).mean()) if rets5 else None
            m10 = float(pd.Series(rets10).mean()) if rets10 else None
            cell = {
                "range": f"{lo:.1f}-{hi:.1f}",
                "sample_count": n,
                "status": "OK",
                "t5_mean": m5,
                "t10_mean": m10,
            }
            if m10 is not None:
                means.append(m10)
        out_buckets.append(cell)

    # Monotonic: higher exit_score → lower forward return
    mono = False
    if len(means) >= 3:
        mono = all(means[i] >= means[i + 1] for i in range(len(means) - 1))

    return {
        "buckets": out_buckets,
        "monotonic_t10": mono,
        "minimum_sample_bucket": bucket_min,
        "note": "Higher exit_score should map to weaker forward returns if calibrated.",
    }
