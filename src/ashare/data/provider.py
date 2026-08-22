from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

import pandas as pd

from ashare.data.akshare_source import fetch_hs300_constituents, fetch_many, fetch_spot_prices
from ashare.data.sample import SAMPLE_SPECS, build_sample_panel
from ashare.data.screen import screen_market
from ashare.data.store import ParquetStore
from ashare.symbols import to_symbol

logger = logging.getLogger("ashare.data")


def resolve_universe(cfg: dict[str, Any]) -> list[str]:
    uni = cfg.get("universe", {})
    mode = str(uni.get("mode", "leader")).lower()
    if mode in {"leader", "event", "leader_event", "dragon"}:
        try:
            from ashare.pool.builder import build_leader_pool

            result = build_leader_pool(cfg)
            cfg["_last_screen"] = result
            try:
                from ashare.data.names import load_name_map, save_name_map

                names = load_name_map(cfg)
                for row in result.get("candidates") or []:
                    if row.get("symbol") and row.get("name"):
                        names[to_symbol(row["symbol"])] = str(row["name"])
                save_name_map(cfg, names)
            except Exception as exc:  # noqa: BLE001
                logger.debug("save pool names failed: %s", exc)
            return [to_symbol(s) for s in result["symbols"]]
        except Exception as exc:  # noqa: BLE001
            logger.warning("Leader/event pool failed (%s), falling back to market screen", exc)
            mode = "market"
    if mode in {"market", "screen", "market_screen"}:
        try:
            result = screen_market(cfg)
            cfg["_last_screen"] = result
            # Persist names from spot for UI
            try:
                from ashare.data.names import load_name_map, save_name_map

                names = load_name_map(cfg)
                for row in result.get("candidates") or []:
                    if row.get("symbol") and row.get("name"):
                        names[to_symbol(row["symbol"])] = str(row["name"])
                save_name_map(cfg, names)
            except Exception as exc:  # noqa: BLE001
                logger.debug("save screen names failed: %s", exc)
            return [to_symbol(s) for s in result["symbols"]]
        except Exception as exc:  # noqa: BLE001
            logger.warning("Market screen failed (%s), falling back to hs300/watchlist", exc)
            mode = "hs300"
    if mode == "hs300":
        try:
            return fetch_hs300_constituents()
        except Exception as exc:  # noqa: BLE001
            logger.warning("HS300 fetch failed (%s), falling back to watchlist", exc)
    symbols = uni.get("symbols") or [s[0] for s in SAMPLE_SPECS]
    return [to_symbol(s) for s in symbols]


def resolve_data_start(cfg: dict[str, Any]) -> str:
    data_cfg = cfg.get("data", {})
    mode = str(cfg.get("universe", {}).get("mode", "leader")).lower()
    if mode in {"market", "screen", "market_screen", "leader", "event", "leader_event", "dragon"}:
        days = int(data_cfg.get("screen_hist_days", 420))
        return (date.today() - timedelta(days=days)).isoformat()
    return str(data_cfg.get("start", cfg.get("backtest", {}).get("start", "2021-01-01")))


def resolve_data_end(cfg: dict[str, Any]) -> str:
    """Prefer explicit data.end, else today (so paper/trading is not stuck on backtest.end)."""
    data_cfg = cfg.get("data", {})
    if data_cfg.get("end"):
        return str(data_cfg["end"])
    return date.today().isoformat()


def _last_bar_date(df: pd.DataFrame) -> date | None:
    if df is None or df.empty:
        return None
    return pd.to_datetime(df["date"]).max().date()


def _needs_refresh(df: pd.DataFrame | None, end: str, *, max_lag_days: int = 5) -> bool:
    """True if cache missing or last bar is older than end by more than a weekend buffer."""
    last = _last_bar_date(df) if df is not None else None
    if last is None:
        return True
    target = date.fromisoformat(end)
    # Don't require future bars
    if last >= target:
        return False
    return (target - last) > timedelta(days=max_lag_days)


def ensure_panel(
    cfg: dict[str, Any],
    symbols: list[str] | None = None,
    *,
    force_refresh: bool = False,
) -> dict:
    data_cfg = cfg.get("data", {})
    store = ParquetStore(data_cfg.get("cache_dir", "data/cache"))
    symbols = [to_symbol(s) for s in (symbols or resolve_universe(cfg))]
    start = resolve_data_start(cfg)
    end = resolve_data_end(cfg)
    provider = str(data_cfg.get("provider", "akshare")).lower()
    max_lag = int(data_cfg.get("refresh_lag_days", 5))

    panel = store.load_panel(symbols)
    stale = [
        s
        for s in symbols
        if force_refresh or _needs_refresh(panel.get(s), end, max_lag_days=max_lag)
    ]
    missing = [s for s in symbols if s not in panel]

    to_fetch = list(dict.fromkeys(stale + missing)) if provider == "akshare" else list(missing)

    if to_fetch and provider == "sample":
        logger.info("Building sample bars for %d symbols", len(to_fetch))
        sample = build_sample_panel(to_fetch, start=start, end=end)
        for sym, df in sample.items():
            store.save_daily(sym, df)
            panel[sym] = df
        to_fetch = [s for s in symbols if s not in panel]
    elif to_fetch and provider == "akshare":
        logger.info("Downloading/refreshing %d symbols via AkShare through %s", len(to_fetch), end)
        try:
            fetched = fetch_many(to_fetch, start=start, end=end)
            for sym, df in fetched.items():
                store.save_daily(sym, df)
                loaded = store.load_daily(sym)
                panel[sym] = loaded if loaded is not None and not loaded.empty else df
            to_fetch = [s for s in to_fetch if s not in fetched]
        except Exception as exc:  # noqa: BLE001
            logger.warning("AkShare download failed: %s", exc)

    still_missing = [s for s in symbols if s not in panel or panel[s] is None or panel[s].empty]
    if still_missing and data_cfg.get("use_sample_if_empty", True):
        # Live calendars (e.g. start=2025, end=2026) must not clip end to 2024 — that yields 0 days.
        sample_start, sample_end = start, end
        if sample_start > sample_end:
            logger.warning(
                "Skip sample fallback for %s: empty range start=%s end=%s",
                still_missing,
                sample_start,
                sample_end,
            )
        else:
            logger.info("Filling %d symbols with sample bars (offline fallback)", len(still_missing))
            sample = build_sample_panel(still_missing, start=sample_start, end=sample_end)
            for sym, df in sample.items():
                if df is None or df.empty:
                    continue
                store.save_daily(sym, df)
                panel[sym] = df
        skipped = [s for s in still_missing if s not in panel or panel[s] is None or panel[s].empty]
        if skipped:
            logger.warning("No bars for %s — omitted from panel", skipped)

    return {s: panel[s] for s in symbols if s in panel and panel[s] is not None and not panel[s].empty}


def latest_marks(cfg: dict[str, Any], symbols: list[str] | None = None) -> dict[str, float]:
    """Last close from panel, overlaid with live Sina spot when available."""
    panel = ensure_panel(cfg, symbols)
    marks = {
        sym: float(df.iloc[-1]["close"])
        for sym, df in panel.items()
        if df is not None and not df.empty
    }
    try:
        spot = fetch_spot_prices(list(marks.keys()))
        for sym, px in spot.items():
            if px > 0:
                marks[sym] = px
        if spot:
            logger.info("Applied %d live spot marks", len(spot))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Spot overlay skipped: %s", exc)
    return marks


def cache_universe(cfg: dict[str, Any], *, force_refresh: bool = True) -> dict:
    symbols = resolve_universe(cfg)
    return ensure_panel(cfg, symbols, force_refresh=force_refresh)
