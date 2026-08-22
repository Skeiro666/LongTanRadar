from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import numpy as np
import pandas as pd

from ashare.ml.features import feature_row_from_closes

FactorFn = Callable[[dict[str, float], dict[str, Any]], float]


@dataclass(frozen=True)
class FactorSpec:
    name: str
    label: str
    description: str
    higher_is_better: bool = True
    compute: FactorFn | None = None


def _f(d: dict[str, float], key: str, default: float = 0.0) -> float:
    try:
        v = float(d.get(key, default) or 0.0)
    except (TypeError, ValueError):
        return default
    if not np.isfinite(v):
        return default
    return v


def _breakout(feats: dict[str, float], meta: dict[str, Any]) -> float:
    return _f(feats, "breakout_20")


def _rs_20(feats: dict[str, float], meta: dict[str, Any]) -> float:
    return _f(feats, "mom_20")


def _vol_confirm(feats: dict[str, float], meta: dict[str, Any]) -> float:
    return _f(feats, "vol_ratio")


def _trend(feats: dict[str, float], meta: dict[str, Any]) -> float:
    g20 = _f(feats, "ma_gap_20")
    g60 = _f(feats, "ma_gap_60")
    if g20 > 0 and g60 > 0:
        return g20 + 0.5 * g60
    return min(g20, 0.0) + min(g60, 0.0)


def _board(feats: dict[str, float], meta: dict[str, Any]) -> float:
    return float(meta.get("board_count") or 0) + 0.4 * float(meta.get("strong_flag") or 0)


def _profit_gap(feats: dict[str, float], meta: dict[str, Any]) -> float:
    return float(meta.get("profit_gap_score") or 0)


def _event(feats: dict[str, float], meta: dict[str, Any]) -> float:
    return float(meta.get("event_score") or 0)


def _liquidity(feats: dict[str, float], meta: dict[str, Any]) -> float:
    amt = float(meta.get("amount") or 0)
    return np.log1p(max(amt, 0.0))


REGISTRY: dict[str, FactorSpec] = {
    "rs_20": FactorSpec("rs_20", "20日相对强度", "近20日涨幅，截面上代表板块内强弱", compute=_rs_20),
    "breakout": FactorSpec("breakout", "突破强度", "相对近20日高点的位置，识别主升/龙头启动", compute=_breakout),
    "vol_confirm": FactorSpec("vol_confirm", "量能确认", "成交量相对20日均量，资金是否跟上", compute=_vol_confirm),
    "trend": FactorSpec("trend", "均线趋势", "站上MA20/MA60 的趋势质量，非估值", compute=_trend),
    "board": FactorSpec("board", "连板/强势", "涨停连板天数与强势池标记", compute=_board),
    "profit_gap": FactorSpec("profit_gap", "利润断层", "预增/扭亏/同比跳升等业绩断层强度", compute=_profit_gap),
    "event": FactorSpec("event", "事件催化", "业绩披露、涨停催化、主题事件分", compute=_event),
    "liquidity": FactorSpec("liquidity", "流动性", "成交额对数，避免微盘不可交易", compute=_liquidity),
}

DEFAULT_WEIGHTS = {
    "rs_20": 0.18,
    "breakout": 0.14,
    "vol_confirm": 0.10,
    "trend": 0.12,
    "board": 0.18,
    "profit_gap": 0.16,
    "event": 0.08,
    "liquidity": 0.04,
}


def list_factors() -> list[dict[str, Any]]:
    return [
        {
            "name": s.name,
            "label": s.label,
            "description": s.description,
            "higher_is_better": s.higher_is_better,
        }
        for s in REGISTRY.values()
    ]


def enrich_leader_features(
    closes: pd.Series,
    volumes: pd.Series | None = None,
    highs: pd.Series | None = None,
    lows: pd.Series | None = None,
) -> dict[str, float] | None:
    """T-day features only. Breakout uses high through T, not future bars."""
    feats = feature_row_from_closes(closes, volumes, highs, lows)
    if feats is None:
        return None
    c = closes.astype(float)
    h = highs.astype(float) if highs is not None else c
    last = float(c.iloc[-1])
    high20 = float(h.tail(20).max()) if len(h) >= 20 else float(h.max())
    feats["breakout_20"] = (last / high20 - 1.0) if high20 > 0 else 0.0
    return feats


def compute_raw_factors(feats: dict[str, float], meta: dict[str, Any] | None = None) -> dict[str, float]:
    meta = meta or {}
    out: dict[str, float] = {}
    for name, spec in REGISTRY.items():
        fn = spec.compute
        out[name] = float(fn(feats, meta)) if fn else 0.0
    return out
