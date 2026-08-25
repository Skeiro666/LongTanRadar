from __future__ import annotations

import math
from typing import Any

import pandas as pd


def _feat(name: str, value: Any, *, as_of: str | None, available: bool = True, source: str = "bars") -> dict[str, Any]:
    return {
        "name": name,
        "value": value,
        "feature_as_of": as_of,
        "available": available and value is not None and not (isinstance(value, float) and math.isnan(value)),
        "source": source,
    }


def compute_pullback_features(
    df: pd.DataFrame,
    *,
    as_of: str | None = None,
    base_feats: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Pullback / re-entry features using T-day and prior bars only.
    Returns both flat values (for engines) and meta dict under pullback_feature_meta.
    """
    from ashare.leader.features import _cutoff_ts

    out: dict[str, Any] = {}
    meta: dict[str, dict[str, Any]] = {}
    if df is None or df.empty:
        return {"available": False, "pullback_feature_meta": meta}

    frame = df.copy()
    frame["date"] = pd.to_datetime(frame["date"])
    cut = _cutoff_ts(as_of)
    if cut is not None:
        frame = frame[pd.to_datetime(frame["date"]).dt.normalize() <= cut]
    frame = frame.sort_values("date").reset_index(drop=True)
    as_of_str = str(as_of or (frame["date"].iloc[-1].date() if len(frame) else ""))
    if len(frame) < 20:
        return {"available": False, "feature_as_of": as_of_str, "pullback_feature_meta": meta}

    c = frame["close"].astype(float)
    h = frame["high"].astype(float)
    lo = frame["low"].astype(float)
    v = frame["volume"].astype(float)
    o = frame["open"].astype(float) if "open" in frame.columns else c
    last = float(c.iloc[-1])
    high20 = float(h.tail(20).max())
    low20 = float(lo.tail(20).min())
    ma5 = float(c.tail(5).mean())
    ma10 = float(c.tail(10).mean()) if len(c) >= 10 else ma5
    ma20 = float(c.tail(20).mean())

    pullback_from_high = (last - high20) / high20 if high20 > 0 else 0.0
    out["pullback_from_high"] = pullback_from_high
    meta["pullback_from_high"] = _feat("pullback_from_high", pullback_from_high, as_of=as_of_str)

    lu = frame.get("limit_up")
    last_lu_close = None
    first_non_lu_after = 0.0
    if lu is not None:
        lu_b = lu.astype(bool)
        lu_idx = [i for i, x in enumerate(lu_b.tolist()) if x]
        if lu_idx:
            last_lu_i = lu_idx[-1]
            last_lu_close = float(c.iloc[last_lu_i])
            # days since last limit-up that are non-limit-up
            after = lu_b.iloc[last_lu_i + 1 :]
            if len(after) and not bool(lu_b.iloc[-1]):
                first_non_lu_after = 1.0
            streak_after = 0
            for x in after:
                if not bool(x):
                    streak_after += 1
                else:
                    break
            out["days_since_limit_up"] = float(streak_after)
        else:
            out["days_since_limit_up"] = 0.0
    else:
        out["days_since_limit_up"] = 0.0

    pullback_from_lu = 0.0
    if last_lu_close and last_lu_close > 0:
        pullback_from_lu = (last - last_lu_close) / last_lu_close
    out["pullback_from_limit_up"] = pullback_from_lu
    meta["pullback_from_limit_up"] = _feat("pullback_from_limit_up", pullback_from_lu, as_of=as_of_str)
    out["first_non_limit_up_after_streak"] = first_non_lu_after
    meta["first_non_limit_up_after_streak"] = _feat(
        "first_non_limit_up_after_streak", first_non_lu_after, as_of=as_of_str
    )

    d_ma5 = (last - ma5) / ma5 if ma5 > 0 else 0.0
    d_ma10 = (last - ma10) / ma10 if ma10 > 0 else 0.0
    d_ma20 = (last - ma20) / ma20 if ma20 > 0 else 0.0
    out["distance_to_ma5"] = d_ma5
    out["distance_to_ma10"] = d_ma10
    out["distance_to_ma20"] = d_ma20
    out["distance_to_MA5"] = d_ma5
    out["distance_to_MA10"] = d_ma10
    out["distance_to_MA20"] = d_ma20
    for k, val in (("distance_to_ma5", d_ma5), ("distance_to_ma10", d_ma10), ("distance_to_ma20", d_ma20)):
        meta[k] = _feat(k, val, as_of=as_of_str)

    vol_peak = float(v.tail(20).max()) if len(v) >= 20 else float(v.max())
    vol_last = float(v.iloc[-1])
    volume_ratio_to_peak = vol_last / vol_peak if vol_peak > 0 else 1.0
    vol_ma5 = float(v.tail(5).mean())
    vol_ma20 = float(v.tail(20).mean()) if len(v) >= 20 else vol_ma5
    volume_contraction = 1.0 - min(1.0, vol_ma5 / vol_ma20) if vol_ma20 > 0 else 0.0
    out["volume_ratio_to_peak"] = volume_ratio_to_peak
    out["volume_contraction"] = max(0.0, volume_contraction)
    meta["volume_ratio_to_peak"] = _feat("volume_ratio_to_peak", volume_ratio_to_peak, as_of=as_of_str)
    meta["volume_contraction"] = _feat("volume_contraction", out["volume_contraction"], as_of=as_of_str)

    # turnover normalization via amount z if present in base
    tz = float((base_feats or {}).get("turnover_zscore") or 0)
    turnover_normalization = max(0.0, min(1.0, 1.0 - abs(tz) / 3.0))
    out["turnover_normalization"] = turnover_normalization
    meta["turnover_normalization"] = _feat("turnover_normalization", turnover_normalization, as_of=as_of_str)

    drawdown_from_extreme = pullback_from_high
    out["drawdown_from_extreme"] = drawdown_from_extreme
    meta["drawdown_from_extreme"] = _feat("drawdown_from_extreme", drawdown_from_extreme, as_of=as_of_str)

    rng = high20 - low20
    close_pos = (last - low20) / rng if rng > 1e-9 else 0.5
    out["close_position_in_range"] = close_pos
    meta["close_position_in_range"] = _feat("close_position_in_range", close_pos, as_of=as_of_str)

    prev_close = float(c.iloc[-2]) if len(c) >= 2 else last
    reclaim_ma5 = 1.0 if prev_close < ma5 and last >= ma5 else 0.0
    reclaim_ma10 = 1.0 if prev_close < ma10 and last >= ma10 else 0.0
    reclaim_ma20 = 1.0 if prev_close < ma20 and last >= ma20 else 0.0
    out["reclaim_ma5"] = reclaim_ma5
    out["reclaim_ma10"] = reclaim_ma10
    out["reclaim_ma20"] = reclaim_ma20

    # breakout after pullback: prior days (T-1 and earlier) had a pullback; today near high + rising.
    # Must NOT require same-day pullback_from_high < -3% AND near high (contradiction / dead feature).
    ret1 = float(c.iloc[-1] / c.iloc[-2] - 1.0) if len(c) >= 2 else 0.0
    had_prior_pullback = False
    if len(frame) >= 6:
        prior_high = float(h.iloc[:-1].tail(20).max())
        prior_min_close = float(c.iloc[:-1].tail(5).min())
        if prior_high > 0 and (prior_min_close / prior_high - 1.0) < -0.03:
            had_prior_pullback = True
    near_high_today = pullback_from_high > -0.015 or last >= high20 * 0.985
    breakout_after_pullback = 1.0 if had_prior_pullback and near_high_today and ret1 > 0.01 else 0.0
    out["breakout_after_pullback"] = breakout_after_pullback
    out["had_prior_pullback"] = 1.0 if had_prior_pullback else 0.0

    # reacceleration: volume up + price up after contraction
    reacceleration = 0.0
    if volume_contraction > 0.15 and ret1 > 0.02 and volume_ratio_to_peak > 0.55:
        reacceleration = 0.7
    if reclaim_ma5 and ret1 > 0.015:
        reacceleration = max(reacceleration, 0.55)
    if breakout_after_pullback:
        reacceleration = max(reacceleration, 0.85)
    out["reacceleration"] = reacceleration
    meta["reacceleration"] = _feat("reacceleration", reacceleration, as_of=as_of_str)

    # reversal strength: bounce from intraday low
    day_low = float(lo.iloc[-1])
    day_high = float(h.iloc[-1])
    day_rng = day_high - day_low
    reversal_strength = (last - day_low) / day_rng if day_rng > 1e-9 else 0.5
    out["reversal_strength"] = reversal_strength
    out["high_close_ratio"] = float((day_high - last) / last) if last > 0 else 0.0

    down = (c.pct_change() < -0.001).astype(int)
    streak = 0
    for x in down.iloc[::-1]:
        if bool(x):
            streak += 1
        else:
            break
    out["consecutive_down_days"] = float(streak)

    # limit_up recovery: previously had boards, today strong close without necessarily limit-up
    lu_count = float((base_feats or {}).get("limit_up_count_5d") or out.get("days_since_limit_up") or 0)
    limit_up_recovery = 0.0
    if lu_count >= 1 and not bool(frame.iloc[-1].get("limit_up")) and ret1 > 0.03 and close_pos > 0.7:
        limit_up_recovery = 0.8
    out["limit_up_recovery"] = limit_up_recovery

    # divergence / distribution flags (same-day structure)
    open_p = float(o.iloc[-1])
    high_open_low_close = 1.0 if open_p > prev_close * 1.02 and last < open_p * 0.97 and volume_ratio_to_peak > 0.7 else 0.0
    out["high_open_low_close"] = high_open_low_close
    big_red = 1.0 if ret1 < -0.05 and volume_ratio_to_peak > 0.65 else 0.0
    out["big_red_volume"] = big_red
    structure_break = 1.0 if last < ma20 * 0.97 and pullback_from_high < -0.08 else 0.0
    out["structure_break"] = structure_break

    # healthy divergence: first non-LU after streak, mild pullback, volume contracts, structure holds
    healthy_divergence = 0.0
    if (
        first_non_lu_after
        and -0.08 <= pullback_from_lu <= 0.02
        and volume_contraction > 0.1
        and structure_break < 0.5
        and high_open_low_close < 0.5
    ):
        healthy_divergence = 0.75
    out["healthy_divergence"] = healthy_divergence
    meta["healthy_divergence"] = _feat("healthy_divergence", healthy_divergence, as_of=as_of_str)

    out["available"] = True
    out["feature_as_of"] = as_of_str
    out["pullback_feature_meta"] = meta
    return out
