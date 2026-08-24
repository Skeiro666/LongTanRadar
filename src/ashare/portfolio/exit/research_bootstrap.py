from __future__ import annotations

"""Research bootstrap entries from OHLCV panel — not fabricated alpha labels."""

from typing import Any

import pandas as pd


def bootstrap_research_entries(
    panel: pd.DataFrame | dict[str, pd.DataFrame] | None,
    *,
    max_symbols: int = 40,
    entries_per_symbol: int = 3,
    min_bars_before_entry: int = 40,
    step_days: int = 15,
    lookback_bars: int = 250,
) -> tuple[list[dict[str, Any]], dict[str, pd.DataFrame]]:
    """
    Build synthetic entry dates on real bars for Exit research backtests.
    Labels / outcomes still come from real forward prices — entries are sampling points only.

    panel: either symbol→DataFrame dict (ensure_panel) or long DataFrame with symbol column.
    """
    bars_by: dict[str, pd.DataFrame] = {}
    if panel is None:
        return [], {}
    if isinstance(panel, dict):
        for sym, df in panel.items():
            if df is None or getattr(df, "empty", True):
                continue
            sub = df.copy()
            if "date" not in sub.columns:
                continue
            sub["date"] = pd.to_datetime(sub["date"]).dt.date
            sub = sub.sort_values("date").tail(lookback_bars).reset_index(drop=True)
            bars_by[str(sym)] = sub
    else:
        if getattr(panel, "empty", True):
            return [], {}
        df = panel.copy()
        if "date" not in df.columns or "symbol" not in df.columns:
            return [], {}
        df["date"] = pd.to_datetime(df["date"]).dt.date
        for sym, sub in df.groupby(df["symbol"].astype(str)):
            sub = sub.sort_values("date").tail(lookback_bars).reset_index(drop=True)
            bars_by[str(sym)] = sub

    symbols = sorted(bars_by.keys())[: max(1, max_symbols)]
    entries: list[dict[str, Any]] = []
    out_bars: dict[str, pd.DataFrame] = {}
    for sym in symbols:
        sub = bars_by[sym]
        if len(sub) < min_bars_before_entry + 30:
            continue
        out_bars[sym] = sub.copy()
        start = min_bars_before_entry
        taken = 0
        i = start
        while i < len(sub) - 25 and taken < entries_per_symbol:
            row = sub.iloc[i]
            entries.append(
                {
                    "symbol": sym,
                    "entry_date": str(row["date"]),
                    "entry_price": float(row["close"]),
                    "source": "research_bootstrap",
                }
            )
            taken += 1
            i += max(1, step_days)
    return entries, out_bars
