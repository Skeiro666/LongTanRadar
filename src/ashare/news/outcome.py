from __future__ import annotations

from typing import Any

import pandas as pd

from ashare.symbols import to_symbol


def event_outcomes(
    events: list[dict[str, Any]],
    panel: dict[str, pd.DataFrame],
    *,
    horizons: list[int] | None = None,
) -> list[dict[str, Any]]:
    """T+1..T+20 excess vs equal-weight not available here; stock return only if bars exist."""
    horizons = horizons or [1, 3, 5, 10, 20]
    out = []
    for ev in events:
        sym = to_symbol(ev.get("symbol") or "")
        df = panel.get(sym)
        if df is None or df.empty:
            out.append({**ev, "outcome_status": "no_bars"})
            continue
        d = df.copy()
        d["date"] = pd.to_datetime(d["date"])
        d = d.sort_values("date")
        t0 = pd.to_datetime(str(ev.get("event_time") or "")[:10], errors="coerce")
        if pd.isna(t0):
            out.append({**ev, "outcome_status": "no_event_time"})
            continue
        hist = d[d["date"] <= t0]
        fut = d[d["date"] > t0]
        if hist.empty:
            out.append({**ev, "outcome_status": "no_asof"})
            continue
        entry = float(hist.iloc[-1]["close"])
        cells = {}
        for h in horizons:
            if len(fut) < h:
                cells[str(h)] = {"status": "pending"}
                continue
            px = float(fut.iloc[h - 1]["close"])
            cells[str(h)] = {"actual_return": px / entry - 1.0, "benchmark_return": None, "excess_return": None}
        out.append({"event_id": ev.get("event_id"), "symbol": sym, "horizons": cells, "outcome_status": "ok"})
    return out
