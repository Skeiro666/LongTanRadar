"""Exit features — as_of safe. Missing inputs → available=false, never fabricated."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

import numpy as np
import pandas as pd

from ashare.portfolio.exit.config import load_exit_config


def _as_date(v: Any) -> date | None:
    if v is None:
        return None
    if isinstance(v, date) and not isinstance(v, datetime):
        return v
    try:
        return pd.Timestamp(v).date()
    except Exception:  # noqa: BLE001
        return None


def _clip01(x: float) -> float:
    return float(max(0.0, min(1.0, x)))


def _feat(name: str, value: float | None, *, available: bool, note: str = "") -> dict[str, Any]:
    return {
        "name": name,
        "value": None if not available or value is None else round(float(value), 6),
        "available": bool(available and value is not None),
        "note": note,
    }


def _bars_asof(bars: pd.DataFrame, as_of: date) -> pd.DataFrame:
    if bars is None or bars.empty:
        return pd.DataFrame()
    df = bars.copy()
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df = df[df["date"] <= as_of].sort_values("date")
    return df


def compute_exit_features(
    *,
    bars: pd.DataFrame | None,
    as_of: date | str,
    position: dict[str, Any] | None = None,
    news: dict[str, Any] | None = None,
    event: dict[str, Any] | None = None,
    portfolio: dict[str, Any] | None = None,
    ml_expected: dict[str, Any] | None = None,
    benchmark_bars: pd.DataFrame | None = None,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build structured exit features at as_of. Labels must NOT be computed here."""
    exit_cfg = load_exit_config(cfg)
    look = dict(exit_cfg.get("lookback") or {})
    as_of_d = _as_date(as_of) or date.today()
    pos = position or {}
    features: dict[str, dict[str, Any]] = {}
    df = _bars_asof(bars if bars is not None else pd.DataFrame(), as_of_d)
    n = len(df)

    current_price: float | None = float(pos.get("current_price") or pos.get("mark") or 0) or None
    atr_value: float | None = None
    entry_px: float | None = float(pos.get("entry_price") or pos.get("cost_price") or 0) or None

    if n < 5:
        for name in (
            "trend_decay",
            "momentum_decay",
            "relative_strength_decay",
            "volume_distribution",
            "price_extension",
            "drawdown",
            "volatility",
            "breakout_failure",
            "moving_average_break",
        ):
            features[name] = _feat(name, None, available=False, note="insufficient_bars")
    else:
        c = df["close"].astype(float)
        h = df["high"].astype(float) if "high" in df.columns else c
        lo = df["low"].astype(float) if "low" in df.columns else c
        v = df["volume"].astype(float) if "volume" in df.columns else pd.Series(1.0, index=df.index)
        ret = c.pct_change()

        ma5 = c.rolling(int(look.get("ma_short", 5))).mean()
        ma10 = c.rolling(int(look.get("ma_mid", 10))).mean()
        ma20 = c.rolling(int(look.get("ma_long", 20))).mean()
        ma60 = c.rolling(int(look.get("ma_xlong", 60))).mean()

        # Trend decay: slope deterioration + distance to MA20
        slope5 = (ma5.iloc[-1] / ma5.iloc[-3] - 1.0) if n >= 3 and ma5.iloc[-3] else 0.0
        slope5_prev = (ma5.iloc[-4] / ma5.iloc[-6] - 1.0) if n >= 6 and ma5.iloc[-6] else slope5
        slope20 = (ma20.iloc[-1] / ma20.iloc[-5] - 1.0) if n >= 5 and not np.isnan(ma20.iloc[-1]) and ma20.iloc[-5] else 0.0
        dist_ma20 = float(c.iloc[-1] / ma20.iloc[-1] - 1.0) if ma20.iloc[-1] and not np.isnan(ma20.iloc[-1]) else 0.0
        trend_raw = 0.0
        if slope5 < slope5_prev:
            trend_raw += 0.35
        if slope20 < 0:
            trend_raw += 0.35
        if dist_ma20 < 0:
            trend_raw += min(0.4, abs(dist_ma20) * 4)
        features["trend_decay"] = _feat("trend_decay", _clip01(trend_raw), available=True)

        # Momentum decay: 5d vs 20d / recent vs prior window
        m5 = float(c.iloc[-1] / c.iloc[-6] - 1.0) if n >= 6 and float(c.iloc[-6]) else None
        m10 = float(c.iloc[-1] / c.iloc[-11] - 1.0) if n >= 11 and float(c.iloc[-11]) else None
        m20 = float(c.iloc[-1] / c.iloc[-21] - 1.0) if n >= 21 and float(c.iloc[-21]) else None
        prior5 = float(c.iloc[-6] / c.iloc[-11] - 1.0) if n >= 11 and float(c.iloc[-11]) else None
        mom_raw = 0.0
        mom_ok = False
        if m5 is not None and prior5 is not None:
            mom_ok = True
            if m5 < prior5:
                mom_raw += 0.4
            if m5 < 0:
                mom_raw += 0.3
        if m5 is not None and m20 is not None:
            mom_ok = True
            if m5 < m20 * 0.5 and m20 > 0:
                mom_raw += 0.3
        features["momentum_decay"] = _feat(
            "momentum_decay",
            _clip01(mom_raw) if mom_ok else None,
            available=mom_ok,
            note="" if mom_ok else "need_11_bars",
        )

        # Relative strength vs benchmark
        rs_ok = False
        rs_raw = None
        bdf = _bars_asof(benchmark_bars if benchmark_bars is not None else pd.DataFrame(), as_of_d)
        if len(bdf) >= 21 and n >= 21:
            bc = bdf["close"].astype(float)
            stock_r = float(c.iloc[-1] / c.iloc[-21] - 1.0)
            bench_r = float(bc.iloc[-1] / bc.iloc[-21] - 1.0)
            excess = stock_r - bench_r
            rs_ok = True
            rs_raw = _clip01(max(0.0, -excess * 3.0))  # underperform → higher exit pressure
        features["relative_strength_decay"] = _feat(
            "relative_strength_decay",
            rs_raw,
            available=rs_ok,
            note="" if rs_ok else "benchmark_unavailable",
        )

        # Volume distribution: down-day volume vs up-day
        up = ret > 0
        down = ret < 0
        vol_up = float(v[up].tail(10).mean()) if up.tail(10).any() else None
        vol_down = float(v[down].tail(10).mean()) if down.tail(10).any() else None
        vol_raw = None
        vol_ok = vol_up is not None and vol_down is not None and vol_up > 0
        if vol_ok:
            ratio = vol_down / vol_up
            vol_raw = _clip01((ratio - 1.0) * 0.8)  # heavier selling volume → higher
            # price high + volume decline
            if n >= 20:
                recent_high = float(h.tail(20).max())
                if float(c.iloc[-1]) >= recent_high * 0.98 and float(v.iloc[-1]) < float(v.tail(20).mean()) * 0.7:
                    vol_raw = _clip01(float(vol_raw) + 0.25)
        features["volume_distribution"] = _feat(
            "volume_distribution", vol_raw, available=bool(vol_ok), note="" if vol_ok else "volume_sparse"
        )

        # Price extension (risk only)
        atr = None
        if n >= 15:
            prev = c.shift(1)
            tr = pd.concat([(h - lo).abs(), (h - prev).abs(), (lo - prev).abs()], axis=1).max(axis=1)
            atr = float(tr.rolling(14).mean().iloc[-1])
        ext_raw = 0.0
        ext_ok = not np.isnan(ma20.iloc[-1]) if n >= 20 else False
        if ext_ok:
            if dist_ma20 > 0.12:
                ext_raw += min(0.5, (dist_ma20 - 0.12) * 3)
            if m5 is not None and m5 > 0.15:
                ext_raw += 0.3
            if atr and atr > 0:
                ext_atr = (float(c.iloc[-1]) - float(ma20.iloc[-1])) / atr
                if ext_atr > 2.5:
                    ext_raw += 0.2
        features["price_extension"] = _feat("price_extension", _clip01(ext_raw) if ext_ok else None, available=ext_ok)

        # Drawdown from peak since entry (or lookback peak)
        entry_px = float(pos.get("entry_price") or pos.get("cost_price") or 0) or None
        peak = float(pos.get("max_favorable_price") or 0) or None
        if peak is None or peak <= 0:
            peak = float(h.tail(min(40, n)).max())
        cur = float(c.iloc[-1])
        if peak > 0:
            dd = (peak - cur) / peak
            features["drawdown"] = _feat("drawdown", _clip01(dd * 2.5), available=True)
        else:
            features["drawdown"] = _feat("drawdown", None, available=False, note="no_peak")

        # Volatility regime
        vol20 = float(ret.tail(20).std()) if n >= 20 else None
        vol60 = float(ret.tail(60).std()) if n >= 60 else vol20
        if vol20 is not None and vol60 and vol60 > 0:
            vratio = vol20 / vol60
            features["volatility"] = _feat("volatility", _clip01((vratio - 1.0) * 1.2), available=True)
        else:
            features["volatility"] = _feat("volatility", None, available=False, note="need_20_bars")

        # Breakout failure
        bf = 0.0
        bf_ok = n >= 25
        if bf_ok:
            prior_high = float(h.iloc[-25:-5].max())
            broke = float(h.iloc[-5:].max()) > prior_high * 1.01
            failed = broke and cur < prior_high
            if failed:
                bf = 0.7
                if vol_down and vol_up and vol_down > vol_up:
                    bf = 0.9
        features["breakout_failure"] = _feat("breakout_failure", _clip01(bf) if bf_ok else None, available=bf_ok)

        # MA break
        ma_break = 0.0
        ma_ok = n >= 20 and not np.isnan(ma20.iloc[-1])
        if ma_ok:
            if cur < float(ma20.iloc[-1]):
                ma_break += 0.5
            if n >= 10 and not np.isnan(ma10.iloc[-1]) and cur < float(ma10.iloc[-1]):
                ma_break += 0.3
            if float(ma5.iloc[-1]) < float(ma20.iloc[-1]):
                ma_break += 0.2
        features["moving_average_break"] = _feat(
            "moving_average_break", _clip01(ma_break) if ma_ok else None, available=ma_ok
        )

        current_price = cur
        atr_value = atr
        entry_px = float(pos.get("entry_price") or pos.get("cost_price") or 0) or None

    # News reversal
    news = news or {}
    ndir = str(news.get("direction") or news.get("current_direction") or "").lower()
    pdir = str(news.get("prior_direction") or news.get("entry_direction") or "").lower()
    news_ok = bool(ndir or pdir or news.get("news_intelligence_score") is not None)
    news_raw = 0.0
    if news_ok:
        if ("pos" in pdir or "bull" in pdir) and ("neg" in ndir or "bear" in ndir):
            news_raw = 0.85
        elif "neg" in ndir or "bear" in ndir:
            news_raw = 0.55
        elif ndir in {"neutral", ""} and ("pos" in pdir or "bull" in pdir):
            news_raw = 0.4
        elif news.get("news_reversal_score") is not None:
            try:
                news_raw = _clip01(float(news["news_reversal_score"]))
            except (TypeError, ValueError):
                news_raw = 0.0
        else:
            news_raw = 0.0
    features["news_reversal"] = _feat(
        "news_reversal", news_raw if news_ok else None, available=news_ok, note="" if news_ok else "no_news"
    )

    # Event completion
    event = event or {}
    estate = str(event.get("event_state") or event.get("state") or "UNKNOWN").upper()
    ev_ok = estate != "UNKNOWN" or bool(event.get("event_type"))
    raise_states = {str(s).upper() for s in (exit_cfg.get("event") or {}).get("states_that_raise_exit") or ["COMPLETED", "INVALIDATED"]}
    if not ev_ok:
        features["event_completion"] = _feat("event_completion", None, available=False, note="event_state_unknown")
    else:
        ev_raw = 0.75 if estate in raise_states else (0.2 if estate in {"CONFIRMED", "ACTIVE"} else 0.1)
        features["event_completion"] = _feat("event_completion", ev_raw, available=True)

    # Time in position
    entry_d = _as_date(pos.get("entry_date") or pos.get("opened_at"))
    if entry_d is not None:
        days = max(0, (as_of_d - entry_d).days)
        soft = float((exit_cfg.get("holding_period") or {}).get("soft_days", 10))
        hard = float((exit_cfg.get("holding_period") or {}).get("hard_days", 40))
        if days <= soft:
            t_raw = 0.05
        elif days >= hard:
            t_raw = 0.55  # soft pressure only — calibrated later
        else:
            t_raw = 0.05 + 0.5 * ((days - soft) / max(hard - soft, 1))
        features["time_in_position"] = _feat("time_in_position", _clip01(t_raw), available=True)
        hold_days = days
    else:
        features["time_in_position"] = _feat("time_in_position", None, available=False, note="no_entry_date")
        hold_days = None

    # Profit / loss (input only — profit ≠ sell)
    max_adverse_return = None
    drawdown_from_peak = None
    if entry_px and current_price and entry_px > 0:
        uret = (current_price - entry_px) / entry_px
        peak_px = float(pos.get("max_favorable_price") or current_price)
        trough_px = float(pos.get("max_adverse_price") or current_price)
        max_fav = (peak_px - entry_px) / entry_px if peak_px > 0 else uret
        max_adverse_return = (trough_px - entry_px) / entry_px if trough_px > 0 else uret
        giveback = max(0.0, max_fav - uret)
        drawdown_from_peak = (peak_px - current_price) / peak_px if peak_px > 0 else None
        # higher giveback / deep loss → mild exit pressure
        pl_raw = 0.0
        if uret < -0.08:
            pl_raw += min(0.5, abs(uret) * 2)
        if giveback > 0.06:
            pl_raw += min(0.4, giveback * 2)
        features["profit_loss"] = _feat("profit_loss", _clip01(pl_raw), available=True)
        unrealized_return = uret
        max_favorable_return = max_fav
        giveback_v = giveback
    else:
        features["profit_loss"] = _feat("profit_loss", None, available=False, note="no_entry_or_mark")
        unrealized_return = None
        max_favorable_return = None
        giveback_v = None

    # Portfolio concentration
    port = portfolio or {}
    weight = port.get("weight")
    max_w = float((exit_cfg.get("portfolio") or {}).get("max_single_weight", 0.35))
    if weight is not None:
        w = float(weight)
        pc = _clip01((w - max_w) / max(max_w, 0.01)) if w > max_w else 0.0
        features["portfolio_concentration"] = _feat("portfolio_concentration", pc, available=True)
    else:
        features["portfolio_concentration"] = _feat(
            "portfolio_concentration", None, available=False, note="weight_unavailable"
        )

    # ML forward return (pressure if expected negative)
    ml = ml_expected or {}
    if ml.get("available") and ml.get("expected_return_10d") is not None:
        er10 = float(ml["expected_return_10d"])
        ml_raw = _clip01(max(0.0, -er10 * 8.0))
        features["ml_forward_return"] = _feat("ml_forward_return", ml_raw, available=True)
    else:
        features["ml_forward_return"] = _feat(
            "ml_forward_return", None, available=False, note="ml_unavailable"
        )

    available_n = sum(1 for f in features.values() if f.get("available"))
    return {
        "as_of": as_of_d.isoformat(),
        "symbol": pos.get("symbol"),
        "features": features,
        "n_available": available_n,
        "current_price": current_price,
        "entry_price": entry_px,
        "atr": atr_value,
        "hold_days": hold_days,
        "unrealized_return": unrealized_return,
        "max_favorable_return": max_favorable_return,
        "max_adverse_return": max_adverse_return,
        "drawdown": drawdown_from_peak,
        "giveback": giveback_v,
        "event_state": estate if event else "UNKNOWN",
        "version": exit_cfg.get("version") or "exit_v1",
    }
