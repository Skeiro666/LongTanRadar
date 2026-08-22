from __future__ import annotations

from typing import Any

import pandas as pd

from ashare.symbols import to_symbol


def _parse_event_day(raw: Any) -> pd.Timestamp | None:
    if raw is None or raw == "":
        return None
    ts = pd.to_datetime(str(raw)[:19], errors="coerce")
    if pd.isna(ts):
        ts = pd.to_datetime(str(raw)[:10], errors="coerce")
    if pd.isna(ts):
        return None
    return pd.Timestamp(ts).normalize()


def classify_price_in_risk(
    *,
    ret_since_event: float | None,
    abs_ret_1d: float | None,
    limit_up: bool,
    limit_down: bool,
    news_direction: str = "NEUTRAL",
) -> str:
    """
    Research warning only. Never maps to SELL/PASS trading action.
    HIGH: large move already occurred in news direction (or limit-up on bullish news).
    """
    if ret_since_event is None and abs_ret_1d is None:
        return "UNKNOWN"
    r = float(ret_since_event if ret_since_event is not None else abs_ret_1d or 0.0)
    d = (news_direction or "NEUTRAL").upper()
    bullish = d in {"BULLISH", "VERY_BULLISH"}
    bearish = d in {"BEARISH", "VERY_BEARISH"}
    if limit_up and bullish:
        return "HIGH"
    if limit_down and bearish:
        return "HIGH"
    if bullish and r >= 0.08:
        return "HIGH"
    if bearish and r <= -0.08:
        return "HIGH"
    if bullish and r >= 0.04:
        return "MEDIUM"
    if bearish and r <= -0.04:
        return "MEDIUM"
    if abs(r) >= 0.12:
        return "HIGH"
    if abs(r) >= 0.05:
        return "MEDIUM"
    return "LOW"


def compute_price_reaction(
    df: pd.DataFrame | None,
    *,
    event_time: str | None = None,
    as_of: str | None = None,
    news_direction: str = "NEUTRAL",
    lookback_days: int = 5,
) -> dict[str, Any]:
    """
    Separate news_signal from price_signal.
    Uses daily bars only. Missing bars → available=false (no fabrication).
    Does NOT emit trading actions.
    """
    base = {
        "available": False,
        "news_signal": news_direction or "NEUTRAL",
        "price_signal": "UNKNOWN",
        "price_in_risk": "UNKNOWN",
        "note": "",
        "warning": "price_in_risk is research warning only — not auto PASS/SELL",
    }
    if df is None or getattr(df, "empty", True):
        base["note"] = "no_bars"
        return base

    d = df.copy()
    d["date"] = pd.to_datetime(d["date"])
    d = d.sort_values("date").reset_index(drop=True)

    event_day = _parse_event_day(event_time) or _parse_event_day(as_of)
    if event_day is None:
        # use last bar as as-of for live discovery
        event_day = pd.Timestamp(d["date"].iloc[-1]).normalize()
        base["note"] = "event_time_missing_used_last_bar"

    hist = d[d["date"] <= event_day]
    if hist.empty:
        base["note"] = "no_asof_bar"
        return base

    row = hist.iloc[-1]
    pre = hist.iloc[-(lookback_days + 1) : -1] if len(hist) > 1 else hist.iloc[0:0]
    close = float(row["close"])
    pre_close = float(pre.iloc[0]["close"]) if len(pre) else None
    vol = float(row.get("volume") or 0)
    pre_vol = float(pre["volume"].mean()) if len(pre) and "volume" in pre.columns else None

    fut = d[d["date"] > event_day]
    post_close = float(fut.iloc[0]["close"]) if len(fut) else None
    ret_1d = (close / float(hist.iloc[-2]["close"]) - 1.0) if len(hist) >= 2 else None
    ret_since = (post_close / close - 1.0) if post_close and close else ret_1d
    ret_lookback = (close / pre_close - 1.0) if pre_close and close else None
    vol_chg = (vol / pre_vol - 1.0) if pre_vol and pre_vol > 0 else None

    limit_up = bool(row.get("limit_up"))
    limit_down = bool(row.get("limit_down"))

    # price_signal from realized move (not news text)
    r_ref = ret_since if ret_since is not None else ret_1d
    if r_ref is None:
        price_signal = "UNKNOWN"
    elif r_ref >= 0.02:
        price_signal = "UP"
    elif r_ref <= -0.02:
        price_signal = "DOWN"
    else:
        price_signal = "FLAT"

    risk = classify_price_in_risk(
        ret_since_event=ret_since if ret_since is not None else ret_lookback,
        abs_ret_1d=ret_1d,
        limit_up=limit_up,
        limit_down=limit_down,
        news_direction=news_direction,
    )

    # score for display only — not mixed into BUY
    score = 0.0
    if r_ref is not None:
        score = max(-1.0, min(1.0, float(r_ref) * 5.0))

    return {
        "available": True,
        "news_signal": (news_direction or "NEUTRAL").upper(),
        "price_signal": price_signal,
        "price_reaction_score": round(score, 4),
        "price_in_risk": risk,
        "event_day": str(event_day.date()),
        "close_at_event": close,
        "ret_1d": None if ret_1d is None else round(float(ret_1d), 6),
        "ret_since_event": None if ret_since is None else round(float(ret_since), 6),
        "ret_lookback": None if ret_lookback is None else round(float(ret_lookback), 6),
        "volume_chg": None if vol_chg is None else round(float(vol_chg), 6),
        "limit_up": limit_up,
        "limit_down": limit_down,
        "note": base.get("note") or "ok",
        "warning": "price_in_risk is research warning only — not auto PASS/SELL. "
        "Do not multiply news_signal × price_move into a stronger BUY. "
        "If price already ran, tell Council information may be priced in.",
    }


def annotate_news_candidate_price(
    nc: dict[str, Any],
    panel: dict[str, Any] | None,
    *,
    as_of: str | None = None,
) -> dict[str, Any]:
    """Fill price_reaction / price_in_risk on a NewsCandidate dict. No trading side effects."""
    out = dict(nc)
    sym = to_symbol(out.get("symbol") or "")
    df = (panel or {}).get(sym)
    rx = compute_price_reaction(
        df,
        event_time=str(out.get("event_time") or out.get("published_at") or "") or None,
        as_of=as_of,
        news_direction=str(out.get("event_direction") or "NEUTRAL"),
    )
    out["price_reaction"] = rx
    out["price_in_risk"] = rx.get("price_in_risk") or "UNKNOWN"
    # never auto-reject solely for HIGH price-in
    return out
