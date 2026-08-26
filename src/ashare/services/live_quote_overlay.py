"""Live Quote Overlay for LeaderMonitor — never mutates Research Snapshot."""

from __future__ import annotations

import logging
from datetime import datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from ashare.symbols import limit_bound_prices, to_symbol

logger = logging.getLogger("ashare.live_quote")

_TZ = ZoneInfo("Asia/Shanghai")
_CACHE: dict[str, dict[str, Any]] = {}
_CACHE_FETCHED_AT: datetime | None = None

LIVE_STATUSES = ("NORMAL", "LIMIT_UP", "BREAK_LIMIT", "WEAK", "STALE", "UNKNOWN")


def live_quote_stale_seconds(cfg: dict[str, Any] | None = None) -> int:
    cfg = cfg or {}
    data = cfg.get("data") or {}
    if "live_quote_stale_seconds" in data:
        return int(data["live_quote_stale_seconds"])
    mon = cfg.get("monitor") or {}
    if "live_quote_stale_seconds" in mon:
        return int(mon["live_quote_stale_seconds"])
    return 90


def _now_cn() -> datetime:
    return datetime.now(_TZ)


def is_a_share_session(now: datetime | None = None) -> bool:
    """Rough A-share continuous auction windows (Mon–Fri). No full calendar."""
    now = now or _now_cn()
    if now.tzinfo is None:
        now = now.replace(tzinfo=_TZ)
    else:
        now = now.astimezone(_TZ)
    if now.weekday() >= 5:
        return False
    t = now.time()
    morning = time(9, 15) <= t <= time(11, 30)
    afternoon = time(13, 0) <= t <= time(15, 5)
    return morning or afternoon


def research_was_limit_up(row: dict[str, Any]) -> bool:
    """Infer research-day limit-up from existing research fields only (read-only)."""
    reason = str(row.get("status_reason") or "")
    if "limit_up_block" in reason:
        return True
    if row.get("research_limit_up") is True:
        return True
    # Explicit research flag if present on watchlist / report rows
    for key in ("limit_up", "is_limit_up", "research_is_limit_up"):
        if row.get(key) is True:
            return True
    return False


def classify_live_status(
    *,
    price: float | None,
    limit_up_price: float | None,
    limit_down_price: float | None,
    change_pct: float | None,
    research_limit_up: bool,
    updated_at: datetime | None,
    now: datetime | None = None,
    stale_seconds: int = 90,
    weak_pct: float = -3.0,
) -> str:
    now = now or _now_cn()
    if price is None or price <= 0:
        return "UNKNOWN"
    if updated_at is not None:
        ts = updated_at if updated_at.tzinfo else updated_at.replace(tzinfo=_TZ)
        age = (now.astimezone(_TZ) - ts.astimezone(_TZ)).total_seconds()
        if age > stale_seconds:
            return "STALE"

    lim_up = float(limit_up_price or 0)
    lim_dn = float(limit_down_price or 0)
    px = float(price)

    if lim_up > 0 and px + 1e-9 >= lim_up - 0.01:
        return "LIMIT_UP"
    if lim_dn > 0 and px - 1e-9 <= lim_dn + 0.01:
        # Treat near floor as WEAK (V1 has no LIMIT_DOWN status enum)
        return "WEAK"
    if research_limit_up and lim_up > 0 and px < lim_up - 0.01:
        return "BREAK_LIMIT"
    if change_pct is not None and float(change_pct) <= weak_pct:
        return "WEAK"
    return "NORMAL"


def build_live_fields(
    row: dict[str, Any],
    quote: dict[str, Any] | None,
    *,
    updated_at: datetime | None,
    now: datetime | None = None,
    stale_seconds: int = 90,
    force_stale: bool = False,
) -> dict[str, Any]:
    """Pure overlay fields — does not touch board_count / research fields."""
    now = now or _now_cn()
    research_lu = research_was_limit_up(row)
    if not quote or float(quote.get("price") or 0) <= 0:
        return {
            "research_date": row.get("research_date"),
            "research_limit_up": research_lu,
            "live_price": None,
            "live_change_pct": None,
            "live_limit_up_price": None,
            "live_limit_down_price": None,
            "live_is_limit_up": False,
            "live_is_limit_down": False,
            "live_status": "UNKNOWN",
            "live_updated_at": None,
            "live_session_open": is_a_share_session(now),
        }

    sym = to_symbol(str(row.get("symbol") or quote.get("symbol") or ""))
    price = float(quote["price"])
    prev = float(quote.get("prev_close") or 0)
    is_st = bool(quote.get("is_st"))
    change_pct = quote.get("change_pct")
    if change_pct is None and prev > 0:
        change_pct = ((price / prev) - 1.0) * 100.0

    lim_up, lim_dn = (0.0, 0.0)
    if prev > 0 and sym:
        lim_up, lim_dn = limit_bound_prices(prev, sym, is_st=is_st)

    live_is_lu = bool(lim_up > 0 and price + 1e-9 >= lim_up - 0.01)
    live_is_ld = bool(lim_dn > 0 and price - 1e-9 <= lim_dn + 0.01)

    status = classify_live_status(
        price=price,
        limit_up_price=lim_up or None,
        limit_down_price=lim_dn or None,
        change_pct=float(change_pct) if change_pct is not None else None,
        research_limit_up=research_lu,
        updated_at=updated_at,
        now=now,
        stale_seconds=stale_seconds,
    )
    if force_stale and status not in ("UNKNOWN",):
        status = "STALE"

    # Never emit bogus zeros when stale without a real quote timestamp path —
    # if STALE from age, still show last known numbers; UI labels them delayed.
    updated_iso = None
    if updated_at is not None:
        ts = updated_at if updated_at.tzinfo else updated_at.replace(tzinfo=_TZ)
        updated_iso = ts.astimezone(_TZ).isoformat(timespec="seconds")

    return {
        "research_date": row.get("research_date"),
        "research_limit_up": research_lu,
        "live_price": round(price, 4),
        "live_change_pct": round(float(change_pct), 4) if change_pct is not None else None,
        "live_limit_up_price": lim_up or None,
        "live_limit_down_price": lim_dn or None,
        "live_is_limit_up": live_is_lu,
        "live_is_limit_down": live_is_ld,
        "live_status": status,
        "live_updated_at": updated_iso,
        "live_session_open": is_a_share_session(now),
    }


def attach_live_quote_overlay(
    rows: list[dict[str, Any]],
    *,
    cfg: dict[str, Any] | None = None,
    research_date: str | None = None,
    fetch: bool = True,
) -> list[dict[str, Any]]:
    """Attach live_* fields onto monitor rows. Mutates row dicts in-place for overlay keys only."""
    global _CACHE, _CACHE_FETCHED_AT

    cfg = cfg or {}
    stale_sec = live_quote_stale_seconds(cfg)
    now = _now_cn()
    session_open = is_a_share_session(now)

    for row in rows:
        if research_date and not row.get("research_date"):
            row["research_date"] = research_date

    symbols = [to_symbol(str(r.get("symbol") or "")) for r in rows if r.get("symbol")]
    symbols = [s for s in symbols if s]

    quotes: dict[str, dict[str, Any]] = {}
    fetched_at = _CACHE_FETCHED_AT
    force_stale = False

    if fetch and symbols and session_open:
        try:
            from ashare.data.akshare_source import fetch_spot_quotes

            fresh = fetch_spot_quotes(symbols)
            if fresh:
                _CACHE.update(fresh)
                _CACHE_FETCHED_AT = now
                fetched_at = now
                quotes = {s: _CACHE[s] for s in symbols if s in _CACHE}
            else:
                quotes = {s: _CACHE[s] for s in symbols if s in _CACHE}
                force_stale = bool(quotes)
                logger.warning("Live quote fetch empty; using cache as STALE if any")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Live quote overlay fetch failed: %s", exc)
            quotes = {s: _CACHE[s] for s in symbols if s in _CACHE}
            force_stale = bool(quotes)
    else:
        # Non-session: avoid repeated Sina hammering — reuse cache; one cold fetch if empty.
        quotes = {s: _CACHE[s] for s in symbols if s in _CACHE}
        if quotes:
            # Age-based STALE handled in classify; force only when clearly leftover cache.
            if fetched_at is not None:
                age = (now - fetched_at.astimezone(_TZ)).total_seconds()
                force_stale = age > stale_sec
            else:
                force_stale = True
        elif fetch and symbols and not session_open:
            try:
                from ashare.data.akshare_source import fetch_spot_quotes

                fresh = fetch_spot_quotes(symbols)
                if fresh:
                    _CACHE.update(fresh)
                    _CACHE_FETCHED_AT = now
                    fetched_at = now
                    quotes = {s: _CACHE[s] for s in symbols if s in _CACHE}
                    force_stale = False
            except Exception as exc:  # noqa: BLE001
                logger.warning("Off-hours live quote fetch failed: %s", exc)

    out: list[dict[str, Any]] = []
    for row in rows:
        sym = to_symbol(str(row.get("symbol") or ""))
        live = build_live_fields(
            row,
            quotes.get(sym),
            updated_at=fetched_at,
            now=now,
            stale_seconds=stale_sec,
            force_stale=force_stale,
        )
        # Overlay only — never overwrite board_count / leader_score / etc.
        for k, v in live.items():
            if k.startswith("live_") or k in ("research_date", "research_limit_up"):
                row[k] = v
        out.append(row)
    return out


def reset_live_quote_cache() -> None:
    """Test helper."""
    global _CACHE, _CACHE_FETCHED_AT
    _CACHE = {}
    _CACHE_FETCHED_AT = None
