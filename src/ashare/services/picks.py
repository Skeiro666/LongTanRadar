from __future__ import annotations

import logging
from typing import Any

from ashare.data.names import attach_names
from ashare.db.redis_client import cache_get, redis_url_from_env
from ashare.services.research import latest_research, run_research

logger = logging.getLogger("ashare.services.picks")


def run_picks(cfg: dict[str, Any], top_n: int | None = None) -> dict[str, Any]:
    """
    默认走龙头研究管线：事件/利润断层池 → 因子库 → AI 圆桌。
    strategy.name=multi_factor 等旧路径仅在显式关闭 research 时保留。
    """
    st = str(cfg.get("strategy", {}).get("name", "leader")).lower()
    use_research = bool((cfg.get("research") or {}).get("enabled", True))
    if use_research and st not in {"dual_ma", "ma"}:
        return run_research(cfg, top_n=top_n)
    return _legacy_ml_picks(cfg, top_n=top_n)


def _legacy_ml_picks(cfg: dict[str, Any], top_n: int | None = None) -> dict[str, Any]:
    """Retained for backtest/debug; not the product default."""
    from datetime import date, datetime, timezone

    from ashare.data.provider import ensure_panel, resolve_universe
    from ashare.ml.features import FEATURE_COLS, feature_row_from_closes
    from ashare.ml.registry import load_model
    from ashare.strategy.anti_chase import (
        allocate_weights,
        enrich_structure,
        passes_anti_chase,
        passes_ml_floor,
        score_cross_section,
    )
    from ashare.strategy.base import StrategyContext
    from ashare.strategy.multi_factor import MultiFactorStrategy
    from ashare.symbols import to_symbol

    symbols = resolve_universe(cfg)
    panel = ensure_panel(cfg, symbols)
    if not panel:
        raise RuntimeError("No market data — run fetch first / check network")

    import pandas as pd

    last_dates = []
    for df in panel.values():
        if not df.empty:
            last_dates.append(pd.to_datetime(df["date"]).max())
    as_of = max(last_dates).date()

    bars: dict[str, Any] = {}
    hist: dict[str, Any] = {}
    cutoff = pd.Timestamp(as_of)
    for sym, df in panel.items():
        sub = df[pd.to_datetime(df["date"]) <= cutoff]
        if sub.empty:
            continue
        hist[sym] = sub
        from ashare.backtest.engine import row_to_bar

        bars[sym] = row_to_bar(sub.iloc[-1])

    strategy_name = str(cfg.get("strategy", {}).get("name", "ml_lgbm"))
    picks_style = str(cfg.get("strategy", {}).get("picks_style", "agree"))
    n = int(top_n or cfg.get("ml", {}).get("top_n", cfg.get("strategy", {}).get("top_n", 5)))
    picks: list[dict[str, Any]] = []

    model = load_model(cfg) if strategy_name in {"ml_lgbm", "lgbm", "ml"} else None
    if model is not None:
        candidates: list[dict[str, Any]] = []
        for sym, bar in bars.items():
            if bar.is_st or bar.is_halt or bar.limit_up:
                continue
            h = hist[sym].sort_values("date")
            closes = h.set_index("date")["close"].astype(float)
            vols = h.set_index("date")["volume"].astype(float)
            highs = h.set_index("date")["high"].astype(float)
            lows = h.set_index("date")["low"].astype(float)
            feats = feature_row_from_closes(closes, vols, highs, lows)
            if feats is None:
                continue
            feats = enrich_structure(feats, closes)
            if picks_style != "momentum" and not passes_anti_chase(feats, cfg):
                continue
            import numpy as np

            x = np.array([[feats[c] for c in FEATURE_COLS]], dtype=float)
            x = np.nan_to_num(x, nan=0.0, posinf=0.0, neginf=0.0)
            ml_score = float(model.predict(x)[0])
            if not passes_ml_floor(ml_score, cfg):
                continue
            candidates.append(
                {
                    "symbol": to_symbol(sym),
                    "ml_score": ml_score,
                    "feats": feats,
                    "features": {k: round(float(feats[k]), 6) for k in FEATURE_COLS},
                    "close": float(closes.iloc[-1]),
                    "reason": f"ml_lgbm_{picks_style}",
                }
            )
        scored = score_cross_section(candidates, cfg)
        ranked = allocate_weights(
            scored,
            top_n=n,
            max_name_weight=float(cfg.get("risk", {}).get("max_name_weight", 0.55)),
        )
        for row in ranked:
            picks.append(
                {
                    "symbol": row["symbol"],
                    "score": row["score"],
                    "ml_score": row["ml_score"],
                    "value_score": row.get("mean_reversion", row.get("value_score")),
                    "ml_z": row.get("ml_z"),
                    "mr_z": row.get("mr_z"),
                    "agreement": row.get("agreement"),
                    "is_breakdown": row.get("is_breakdown"),
                    "features": row.get("features"),
                    "close": row.get("close"),
                    "why": row.get("why"),
                    "weight": row["weight"],
                    "reason": row.get("reason") or f"ml_lgbm_{picks_style}",
                }
            )
        strategy_name = f"ml_lgbm_{picks_style}"
    else:
        st = cfg.get("strategy", {})
        mf = MultiFactorStrategy(
            top_n=n,
            lookback_mom=int(st.get("lookback_mom", 20)),
            lookback_vol=int(st.get("lookback_vol", 20)),
            lookback_value=int(st.get("lookback_value", 60)),
            w_mom=float(st.get("w_mom", 0.1)),
            w_vol=float(st.get("w_vol", 0.35)),
            w_value=float(st.get("w_value", 0.55)),
            max_name_weight=float(cfg.get("risk", {}).get("max_name_weight", 0.2)),
            max_gross_weight=float(cfg.get("risk", {}).get("max_gross_weight", 0.95)),
        )
        ctx = StrategyContext(
            as_of=as_of,
            equity=1_000_000.0,
            cash=1_000_000.0,
            positions={},
            bars_today=bars,
            history=hist,
            is_month_end=True,
        )
        intents = mf.on_date(ctx)
        buy_syms = [i.symbol for i in intents if i.side.value == "BUY"]
        w = 1.0 / len(buy_syms) if buy_syms else 0.0
        for sym in buy_syms[:n]:
            picks.append({"symbol": to_symbol(sym), "score": 0.0, "weight": w, "reason": "multi_factor"})
        strategy_name = "multi_factor"

    picks = attach_names(picks, cfg)
    screen = cfg.get("_last_screen") or {}
    return {
        "as_of": as_of.isoformat(),
        "strategy": strategy_name,
        "picks_style": picks_style,
        "universe_mode": str(cfg.get("universe", {}).get("mode", "market")),
        "universe_size": len(symbols),
        "scored": len(bars),
        "screen": {
            "raw_count": screen.get("raw_count"),
            "filtered_count": screen.get("filtered_count"),
            "filters": screen.get("filters"),
        },
        "picks": picks,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def latest_picks(cfg: dict[str, Any]) -> dict[str, Any] | None:
    data = latest_research(cfg)
    if data:
        data = dict(data)
        data["picks"] = attach_names(list(data.get("picks") or []), cfg)
        return data
    rurl = redis_url_from_env(cfg)
    try:
        cached = cache_get(rurl, "ashare:picks:latest")
        if cached:
            cached = dict(cached)
            cached["picks"] = attach_names(list(cached.get("picks") or []), cfg)
            return cached
    except Exception:  # noqa: BLE001
        pass
    return None
