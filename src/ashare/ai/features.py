from __future__ import annotations

from ashare.strategy.base import StrategyContext
from ashare.symbols import to_symbol


def snapshot_features(ctx: StrategyContext, lookback_mom: int = 20, lookback_vol: int = 20, lookback_value: int = 60) -> list[dict]:
    """Compact numeric snapshot for the LLM (no future bars)."""
    rows: list[dict] = []
    need = max(lookback_mom, lookback_vol, lookback_value) + 2
    for sym in ctx.tradable():
        closes = ctx.closes(sym)
        if len(closes) < need:
            continue
        ret = closes.pct_change().dropna()
        last = float(closes.iloc[-1])
        ma = float(closes.tail(lookback_value).mean())
        bar = ctx.bars_today[sym]
        rows.append(
            {
                "symbol": to_symbol(sym),
                "close": round(last, 4),
                "mom": round(float(closes.iloc[-1] / closes.iloc[-lookback_mom] - 1.0), 4),
                "vol": round(float(ret.tail(lookback_vol).std()), 4),
                "value_proxy": round((ma - last) / ma if ma else 0.0, 4),
                "pct_chg": round(float(bar.pct_chg), 4),
                "limit_up": bool(bar.limit_up),
                "limit_down": bool(bar.limit_down),
            }
        )
    rows.sort(key=lambda r: r["mom"], reverse=True)
    return rows
