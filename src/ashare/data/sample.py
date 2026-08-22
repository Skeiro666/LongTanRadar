from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from ashare.symbols import board_limit_pct, to_symbol


SAMPLE_SPECS: list[tuple[str, float, float]] = [
    ("601288.SH", 4.2, 0.012),
    ("601398.SH", 5.5, 0.011),
    ("601988.SH", 4.8, 0.012),
    ("601328.SH", 6.5, 0.013),
    ("600016.SH", 3.8, 0.014),
    ("000001.SZ", 11.5, 0.016),
    ("601166.SH", 18.1, 0.015),
    ("601818.SH", 3.5, 0.014),
    ("600919.SH", 8.5, 0.015),
    ("002142.SZ", 22.0, 0.018),
    ("600519.SH", 1800.0, 0.012),
    ("000858.SZ", 160.0, 0.016),
]


def _trading_days(start: str, end: str) -> list[date]:
    days: list[date] = []
    cur = date.fromisoformat(start)
    last = date.fromisoformat(end)
    while cur <= last:
        if cur.weekday() < 5:
            days.append(cur)
        cur += timedelta(days=1)
    return days


def build_sample_panel(
    symbols: list[str] | None = None,
    start: str = "2021-01-01",
    end: str = "2024-12-31",
    seed: int = 42,
) -> dict[str, pd.DataFrame]:
    """Offline synthetic A-share daily bars so backtest/paper run without network."""
    wanted = [to_symbol(s) for s in (symbols or [s[0] for s in SAMPLE_SPECS])]
    spec_map = {to_symbol(s): (px, vol) for s, px, vol in SAMPLE_SPECS}
    rng = np.random.default_rng(seed)
    if start > end:
        start, end = end, start
    days = _trading_days(start, end)
    if not days:
        # Degenerate range: synthesize ~1y weekdays ending at end (or start)
        anchor = date.fromisoformat(end if end else start)
        days = _trading_days((anchor - timedelta(days=400)).isoformat(), anchor.isoformat())
    panel: dict[str, pd.DataFrame] = {}
    if not days:
        return panel

    for i, sym in enumerate(wanted):
        px0, vol = spec_map.get(sym, (20.0 + i, 0.016))
        n = len(days)
        if n <= 0:
            continue
        drift = 0.00015 if i % 3 != 2 else -0.00005
        rets = rng.normal(drift, vol / np.sqrt(252), n)
        # occasional limit-up / limit-down days
        n_shock = min(n, max(1, n // 80))
        shock_idx = rng.choice(n, size=n_shock, replace=False) if n_shock > 0 else np.array([], dtype=int)
        for j in shock_idx:
            rets[j] = 0.101 if rng.random() > 0.4 else -0.101
        close = px0 * np.cumprod(1.0 + rets)
        open_px = np.concatenate([[px0], close[:-1]]) * (1.0 + rng.normal(0, 0.003, n))
        high = np.maximum(open_px, close) * (1.0 + np.abs(rng.normal(0, 0.004, n)))
        low = np.minimum(open_px, close) * (1.0 - np.abs(rng.normal(0, 0.004, n)))
        volume = rng.uniform(5e5, 8e6, n)
        n_halt = min(3, n)
        halt_days = set(rng.choice(n, size=n_halt, replace=False).tolist()) if n_halt > 0 else set()
        lim = board_limit_pct(sym)
        rows = []
        prev = px0
        for k, d in enumerate(days):
            is_halt = k in halt_days
            c = float(close[k])
            o = float(open_px[k])
            h = float(high[k])
            lo = float(low[k])
            pct = (c / prev - 1.0) * 100.0 if prev else 0.0
            if is_halt:
                o = h = lo = c = prev
                pct = 0.0
                vol_k = 0.0
            else:
                vol_k = float(volume[k])
            limit_up = (not is_halt) and pct >= (lim - 0.05)
            limit_down = (not is_halt) and pct <= -(lim - 0.05)
            if limit_up:
                c = prev * (1.0 + lim / 100.0)
                h = c
            if limit_down:
                c = prev * (1.0 - lim / 100.0)
                lo = c
            rows.append(
                {
                    "date": pd.Timestamp(d),
                    "symbol": sym,
                    "open": round(o, 4),
                    "high": round(h, 4),
                    "low": round(lo, 4),
                    "close": round(c, 4),
                    "volume": vol_k,
                    "amount": vol_k * c,
                    "pct_chg": round(pct if not (limit_up or limit_down) else (lim if limit_up else -lim), 4),
                    "is_st": False,
                    "is_halt": is_halt,
                    "limit_up": limit_up,
                    "limit_down": limit_down,
                }
            )
            prev = c
        panel[sym] = pd.DataFrame(rows)
    return panel
