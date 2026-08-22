from __future__ import annotations

import logging
import re
from typing import Any

from ashare.data.screen import fetch_a_share_spot
from ashare.pool.events import (
    fetch_limit_up_events,
    fetch_profit_gap_events,
    fetch_strong_events,
    merge_event_rows,
)
from ashare.symbols import to_symbol

logger = logging.getLogger("ashare.pool.builder")

_ST = re.compile(r"ST|退市", re.I)


def _pool_cfg(cfg: dict[str, Any] | None) -> dict[str, Any]:
    defaults = {
        "use_limit_up": True,
        "use_strong": True,
        "use_profit_gap": True,
        "use_tech_leader": True,
        "max_candidates": 40,
        "min_amount": 8.0e7,
        "min_price": 3.0,
        "max_price": 80.0,
        "exclude_st": True,
        "exclude_bj": True,
        "exclude_kcb": True,
        "exclude_cyb": False,
        "tech_min_pct_chg": 3.0,
        "tech_top": 25,
        "min_board": 1,
    }
    raw = dict((cfg or {}).get("pool") or {})
    return {**defaults, **raw}


def _from_spot_leaders(cfg: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Technical leader fallback: high day return + liquidity (not pullback)."""
    pc = _pool_cfg(cfg)
    try:
        spot = fetch_a_share_spot()
    except Exception as exc:  # noqa: BLE001
        logger.warning("spot leaders failed: %s", exc)
        return []
    rows: list[dict[str, Any]] = []
    for _, r in spot.iterrows():
        code = str(r.get("code") or "").strip().lower()
        name = str(r.get("name") or "")
        price = float(r.get("price") or 0)
        amount = float(r.get("amount") or 0)
        pct = float(r.get("pct_chg") or 0)
        if price <= 0 or amount < float(pc["min_amount"]):
            continue
        if pct < float(pc["tech_min_pct_chg"]):
            continue
        if pc["exclude_st"] and _ST.search(name):
            continue
        sym = None
        if code.startswith(("sh", "sz", "bj")) and len(code) >= 8:
            sym = to_symbol(f"{code[2:]}.{code[:2].upper()}")
        elif code.isdigit() and len(code) == 6:
            sym = to_symbol(code)
        if not sym:
            continue
        c, ex = sym.split(".")
        if pc["exclude_bj"] and (ex == "BJ" or c.startswith(("4", "8", "92"))):
            continue
        if pc["exclude_kcb"] and c.startswith("688"):
            continue
        if pc["exclude_cyb"] and c.startswith(("300", "301")):
            continue
        if price < float(pc["min_price"]):
            continue
        if float(pc["max_price"]) and price > float(pc["max_price"]):
            continue
        board = 1 if pct >= 9.5 else 0
        rows.append(
            {
                "symbol": sym,
                "name": name,
                "source": "tech_leader",
                "price": price,
                "amount": amount,
                "pct_chg": pct,
                "board_count": board,
                "strong_flag": 1 if pct >= 5 else 0,
                "profit_gap_score": 0.0,
                "event_score": min(2.0, pct / 5.0),
                "event_tags": ["技术龙头", f"涨{pct:.1f}%"],
                "thesis": f"现货强势 · 涨幅{pct:.1f}% · 额{amount/1e8:.2f}亿",
            }
        )
    rows.sort(key=lambda x: (x["pct_chg"], x["amount"]), reverse=True)
    return rows[: int(pc["tech_top"])]


def _apply_hard_filters(rows: list[dict[str, Any]], cfg: dict[str, Any] | None) -> list[dict[str, Any]]:
    pc = _pool_cfg(cfg)
    out = []
    for r in rows:
        sym = r.get("symbol")
        if not sym:
            continue
        name = str(r.get("name") or "")
        if pc["exclude_st"] and _ST.search(name):
            continue
        code, ex = str(sym).split(".")
        if pc["exclude_bj"] and (ex == "BJ" or code.startswith(("4", "8", "92"))):
            continue
        if pc["exclude_kcb"] and code.startswith("688"):
            continue
        if pc["exclude_cyb"] and code.startswith(("300", "301")):
            continue
        price = r.get("price")
        if price is not None:
            if float(price) < float(pc["min_price"]):
                continue
            if float(pc["max_price"]) and float(price) > float(pc["max_price"]):
                continue
        out.append(r)
    return out


def build_leader_pool(cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """
    利润断层 / 事件驱动 / 龙头强势 股票池。
    不再做「全市场回调捡便宜」；优先涨停连板、强势股、业绩断层，不足时用技术龙头补齐。
    """
    pc = _pool_cfg(cfg)
    raw_parts: list[dict[str, Any]] = []
    sources_ok: dict[str, int] = {}

    if pc["use_limit_up"]:
        rows = fetch_limit_up_events(cfg)
        sources_ok["limit_up"] = len(rows)
        raw_parts.extend(rows)
    if pc["use_strong"]:
        rows = fetch_strong_events(cfg)
        sources_ok["strong"] = len(rows)
        raw_parts.extend(rows)
    if pc["use_profit_gap"]:
        rows = fetch_profit_gap_events(cfg)
        sources_ok["profit_gap"] = len(rows)
        raw_parts.extend(rows)

    merged = merge_event_rows(raw_parts)
    if pc["use_tech_leader"] and len(merged) < int(pc["max_candidates"]) // 2:
        tech = _from_spot_leaders(cfg)
        sources_ok["tech_leader"] = len(tech)
        merged = merge_event_rows(merged + tech)
    elif pc["use_tech_leader"] and not merged:
        tech = _from_spot_leaders(cfg)
        sources_ok["tech_leader"] = len(tech)
        merged = merge_event_rows(tech)

    filtered = _apply_hard_filters(merged, cfg)
    # Prefer names with event substance: boards or profit gap or high event score
    filtered.sort(
        key=lambda x: (
            float(x.get("profit_gap_score") or 0) * 2
            + float(x.get("board_count") or 0)
            + float(x.get("event_score") or 0)
            + (float(x.get("amount") or 0) / 1e10)
        ),
        reverse=True,
    )
    max_n = int(pc["max_candidates"])
    picked = filtered[:max_n]
    symbols = [r["symbol"] for r in picked]
    logger.info(
        "Leader pool: sources=%s merged=%d filtered=%d picked=%d",
        sources_ok,
        len(merged),
        len(filtered),
        len(picked),
    )
    return {
        "mode": "leader_event",
        "raw_count": sum(sources_ok.values()),
        "filtered_count": len(filtered),
        "candidates": picked,
        "symbols": symbols,
        "sources": sources_ok,
        "filters": pc,
    }
