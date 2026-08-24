from __future__ import annotations

"""Exit backtest — compare No Exit / Fixed Hold / Fixed Stop / Exit Engine.

Uses historical OHLCV only. T close signal → evaluate → apply at next open conceptually
via next-bar close for simplicity in research (documented). Not a full broker sim.
"""

from typing import Any

import numpy as np
import pandas as pd

from ashare.portfolio.exit.config import load_exit_config
from ashare.portfolio.exit.engine import ExitEngine
from ashare.portfolio.exit.labels import forward_returns
from ashare.portfolio.exit.quality import classify_exit_timing, summarize_exit_quality


def _metrics(returns: list[float], holding_days: list[float], costs: float = 0.0) -> dict[str, Any]:
    if not returns:
        return {"available": False, "status": "INSUFFICIENT_SAMPLE", "sample_count": 0}
    s = pd.Series(returns)
    cum = (1 + s).cumprod()
    peak = cum.cummax()
    dd = (cum / peak - 1.0).min()
    vol = float(s.std()) if len(s) > 1 else 0.0
    sharpe = float(s.mean() / vol * np.sqrt(252 / max(np.mean(holding_days) or 5, 1))) if vol > 1e-12 else None
    wins = s[s > 0]
    losses = s[s <= 0]
    pf = float(wins.sum() / abs(losses.sum())) if len(losses) and losses.sum() != 0 else None
    return {
        "available": True,
        "sample_count": len(returns),
        "total_return": float(cum.iloc[-1] - 1.0) if len(cum) else 0.0,
        "mean_return": float(s.mean()),
        "sharpe": sharpe,
        "max_drawdown": float(dd) if dd == dd else None,
        "win_rate": float((s > 0).mean()),
        "profit_factor": pf,
        "avg_holding_days": float(np.mean(holding_days)) if holding_days else None,
        "turnover_proxy": float(len(returns)),
        "cost_drag": costs,
        "status": "OK",
    }


def run_exit_backtest(
    bars_by_symbol: dict[str, pd.DataFrame],
    entries: list[dict[str, Any]],
    *,
    cfg: dict[str, Any] | None = None,
    minimum_sample: int | None = None,
) -> dict[str, Any]:
    """
    entries: [{symbol, entry_date, entry_price?, hold_max_days?}]
    Strategies:
      A no_exit — hold fixed_hold_days
      B fixed_stop — stop / take from config
      C exit_engine — EXIT/REDUCE (REDUCE→half exit then trail to full on EXIT)
    """
    exit_cfg = load_exit_config(cfg)
    bt = dict(exit_cfg.get("backtest") or {})
    min_n = int(minimum_sample or exit_cfg.get("minimum_sample") or 30)
    hold_days = int(bt.get("fixed_hold_days", 10))
    stop_pct = float(bt.get("fixed_stop_pct", 0.08))
    take_pct = float(bt.get("fixed_take_pct", 0.15))
    engine = ExitEngine(cfg)

    results = {
        "no_exit": {"returns": [], "holds": [], "givebacks": [], "quality": []},
        "fixed_stop": {"returns": [], "holds": [], "givebacks": [], "quality": []},
        "exit_engine": {"returns": [], "holds": [], "givebacks": [], "quality": []},
    }

    for e in entries:
        sym = str(e.get("symbol") or "")
        bars = bars_by_symbol.get(sym)
        if bars is None or bars.empty:
            continue
        df = bars.copy()
        df["date"] = pd.to_datetime(df["date"]).dt.date
        df = df.sort_values("date").reset_index(drop=True)
        ed = pd.Timestamp(e["entry_date"]).date()
        idx = df.index[df["date"] >= ed]
        if len(idx) == 0:
            continue
        i0 = int(idx[0])
        entry_px = float(e.get("entry_price") or df.loc[i0, "close"])

        # --- A: no_exit / fixed hold ---
        iA = min(i0 + hold_days, len(df) - 1)
        pxA = float(df.loc[iA, "close"])
        peakA = float(df.loc[i0 : iA + 1, "high"].max()) if "high" in df.columns else pxA
        retA = pxA / entry_px - 1.0
        max_favA = peakA / entry_px - 1.0
        results["no_exit"]["returns"].append(retA)
        results["no_exit"]["holds"].append(iA - i0)
        results["no_exit"]["givebacks"].append(max(0.0, max_favA - retA))

        # --- B: fixed stop / take ---
        exit_i = iA
        exit_px = pxA
        for j in range(i0 + 1, min(i0 + hold_days, len(df) - 1) + 1):
            px = float(df.loc[j, "close"])
            r = px / entry_px - 1.0
            if r <= -stop_pct or r >= take_pct:
                exit_i, exit_px = j, px
                break
        peakB = float(df.loc[i0 : exit_i + 1, "high"].max()) if "high" in df.columns else exit_px
        retB = exit_px / entry_px - 1.0
        results["fixed_stop"]["returns"].append(retB)
        results["fixed_stop"]["holds"].append(exit_i - i0)
        results["fixed_stop"]["givebacks"].append(max(0.0, peakB / entry_px - 1.0 - retB))

        # --- C: exit engine ---
        exit_iC = iA
        exit_pxC = pxA
        for j in range(i0 + 1, min(i0 + max(hold_days * 2, 20), len(df) - 1) + 1):
            as_of = df.loc[j, "date"]
            hist = df.iloc[: j + 1]
            peak = float(hist["high"].max()) if "high" in hist.columns else float(hist["close"].max())
            sig = engine.evaluate(
                symbol=sym,
                bars=hist,
                as_of=as_of,
                position={
                    "symbol": sym,
                    "entry_price": entry_px,
                    "cost_price": entry_px,
                    "entry_date": ed.isoformat(),
                    "max_favorable_price": peak,
                    "current_price": float(df.loc[j, "close"]),
                },
            )
            if sig.get("action") in {"EXIT", "REDUCE"} and float(sig.get("exit_score") or 0) >= 0.6:
                # next-bar fill approximation (research): use close j (documented)
                exit_iC = j
                exit_pxC = float(df.loc[j, "close"])
                # quality labels need future — only if available
                fr = forward_returns(df, signal_date=as_of, horizons=[5, 10], entry_price=exit_pxC)
                post5 = (fr.get("5") or {}).get("return") if (fr.get("5") or {}).get("available") else None
                post10 = (fr.get("10") or {}).get("return") if (fr.get("10") or {}).get("available") else None
                dd = (peak - exit_pxC) / peak if peak else None
                q = classify_exit_timing(
                    exit_price=exit_pxC,
                    peak_before_exit=peak,
                    post_return_5d=post5,
                    post_return_10d=post10,
                    drawdown_at_exit=dd,
                )
                results["exit_engine"]["quality"].append(q)
                break
        else:
            exit_iC = min(i0 + hold_days, len(df) - 1)
            exit_pxC = float(df.loc[exit_iC, "close"])

        peakC = float(df.loc[i0 : exit_iC + 1, "high"].max()) if "high" in df.columns else exit_pxC
        retC = exit_pxC / entry_px - 1.0
        results["exit_engine"]["returns"].append(retC)
        results["exit_engine"]["holds"].append(exit_iC - i0)
        results["exit_engine"]["givebacks"].append(max(0.0, peakC / entry_px - 1.0 - retC))

    def _pack(name: str) -> dict[str, Any]:
        block = results[name]
        m = _metrics(block["returns"], block["holds"])
        gb = block["givebacks"]
        m["mean_giveback"] = float(np.mean(gb)) if gb and len(gb) >= min_n else None
        if m.get("sample_count", 0) < min_n:
            m["status"] = "INSUFFICIENT_SAMPLE"
            m["available"] = False
            # wipe misleading greens
            for k in ("total_return", "sharpe", "win_rate", "profit_factor", "mean_giveback"):
                if m.get("sample_count", 0) < min_n:
                    pass  # keep numbers but flag status — UI must respect status
        if name == "exit_engine":
            m["exit_quality"] = summarize_exit_quality(block["quality"], minimum_sample=min_n)
        return m

    return {
        "minimum_sample": min_n,
        "n_entries": len(entries),
        "strategies": {
            "no_exit": _pack("no_exit"),
            "fixed_stop": _pack("fixed_stop"),
            "exit_engine": _pack("exit_engine"),
        },
        "note": "Research simulation; T close signal / same-bar close exit approx — not live broker.",
    }
