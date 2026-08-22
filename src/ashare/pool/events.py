from __future__ import annotations

import logging
import re
from datetime import date, timedelta
from typing import Any

import pandas as pd

from ashare.symbols import to_symbol

logger = logging.getLogger("ashare.pool.events")

_ST = re.compile(r"ST|退市", re.I)
_GAP_TYPES = ("预增", "扭亏", "续盈", "略增", "大幅上升", "增长")
_BAD_TYPES = ("预减", "首亏", "续亏", "略减", "大幅下降")


def _ak():
    import akshare as ak  # type: ignore

    return ak


def recent_trade_dates(n: int = 8) -> list[str]:
    out: list[str] = []
    d = date.today()
    for i in range(0, 40):
        day = d - timedelta(days=i)
        if day.weekday() < 5:
            out.append(day.strftime("%Y%m%d"))
        if len(out) >= n:
            break
    return out


def recent_report_periods(n: int = 4) -> list[str]:
    """Likely A-share report period ends (YYYYMMDD)."""
    today = date.today()
    ends = []
    y = today.year
    for year in (y, y - 1, y - 2):
        for md in ("1231", "0930", "0630", "0331"):
            ends.append(f"{year}{md}")
    # keep those not too far in the future relative to today
    filtered = [p for p in ends if p <= today.strftime("%Y%m%d")]
    return filtered[:n]


def _code_to_symbol(code: Any) -> str | None:
    raw = str(code).strip()
    if not raw:
        return None
    raw = re.sub(r"\D", "", raw)
    if len(raw) != 6:
        return None
    try:
        return to_symbol(raw)
    except Exception:  # noqa: BLE001
        return None


def _pick_col(df: pd.DataFrame, *cands: str) -> str | None:
    cols = {str(c): c for c in df.columns}
    for name in cands:
        if name in cols:
            return cols[name]
    for name in cands:
        for c in df.columns:
            if name in str(c):
                return c
    return None


def fetch_limit_up_events(cfg: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """涨停池 → 龙头连板候选。"""
    ak = _ak()
    out: list[dict[str, Any]] = []
    for d in recent_trade_dates(8):
        try:
            df = ak.stock_zt_pool_em(date=d)
        except Exception as exc:  # noqa: BLE001
            logger.debug("zt pool %s failed: %s", d, exc)
            continue
        if df is None or df.empty:
            continue
        code_c = _pick_col(df, "代码", "股票代码")
        name_c = _pick_col(df, "名称", "股票名称")
        board_c = _pick_col(df, "连板数", "连板")
        amt_c = _pick_col(df, "成交额", "金额")
        reason_c = _pick_col(df, "涨停原因", "原因", "所属行业")
        for _, r in df.iterrows():
            sym = _code_to_symbol(r.get(code_c) if code_c else None)
            if not sym:
                continue
            name = str(r.get(name_c) or "")
            if _ST.search(name):
                continue
            boards = 1
            if board_c is not None:
                try:
                    boards = int(float(r.get(board_c) or 1))
                except (TypeError, ValueError):
                    boards = 1
            amount = 0.0
            if amt_c is not None:
                try:
                    amount = float(r.get(amt_c) or 0)
                except (TypeError, ValueError):
                    amount = 0.0
            reason = str(r.get(reason_c) or "") if reason_c else ""
            out.append(
                {
                    "symbol": sym,
                    "name": name,
                    "source": "limit_up",
                    "as_of": d,
                    "board_count": max(1, boards),
                    "strong_flag": 1,
                    "amount": amount,
                    "event_score": min(3.0, 1.0 + 0.5 * max(0, boards - 1)),
                    "event_tags": ["涨停", f"{boards}板"] + ([reason] if reason else []),
                    "thesis": f"{d} 涨停池 · {boards}板" + (f" · {reason}" if reason else ""),
                }
            )
        if out:
            logger.info("Limit-up pool %s: %d names", d, len(out))
            break
    return out


def fetch_strong_events(cfg: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """强势股池（曾涨停/高位强势）。"""
    ak = _ak()
    out: list[dict[str, Any]] = []
    for d in recent_trade_dates(6):
        try:
            df = ak.stock_zt_pool_strong_em(date=d)
        except Exception as exc:  # noqa: BLE001
            logger.debug("strong pool %s failed: %s", d, exc)
            continue
        if df is None or df.empty:
            continue
        code_c = _pick_col(df, "代码", "股票代码")
        name_c = _pick_col(df, "名称", "股票名称")
        amt_c = _pick_col(df, "成交额", "金额")
        for _, r in df.iterrows():
            sym = _code_to_symbol(r.get(code_c) if code_c else None)
            if not sym:
                continue
            name = str(r.get(name_c) or "")
            if _ST.search(name):
                continue
            amount = 0.0
            if amt_c is not None:
                try:
                    amount = float(r.get(amt_c) or 0)
                except (TypeError, ValueError):
                    amount = 0.0
            out.append(
                {
                    "symbol": sym,
                    "name": name,
                    "source": "strong",
                    "as_of": d,
                    "board_count": 0,
                    "strong_flag": 1,
                    "amount": amount,
                    "event_score": 1.2,
                    "event_tags": ["强势股"],
                    "thesis": f"{d} 强势股池",
                }
            )
        if out:
            logger.info("Strong pool %s: %d names", d, len(out))
            break
    return out


def _profit_gap_score(change_pct: float | None, forecast_type: str) -> float:
    t = forecast_type or ""
    if any(b in t for b in _BAD_TYPES):
        return 0.0
    score = 0.0
    if any(g in t for g in _GAP_TYPES):
        score += 1.5
    if "扭亏" in t:
        score += 1.0
    if change_pct is not None and change_pct > 0:
        # 同比跳升：>50% 开始计分，>200% 接近满额
        score += min(3.0, change_pct / 100.0)
    return score


def fetch_profit_gap_events(cfg: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """业绩预告中的利润断层（预增/扭亏/高同比）。"""
    ak = _ak()
    sc = ((cfg or {}).get("pool") or {})
    min_yoy = float(sc.get("min_profit_yoy_pct", 50.0))
    out: list[dict[str, Any]] = []
    for period in recent_report_periods(6):
        try:
            df = ak.stock_yjyg_em(date=period)
        except Exception as exc:  # noqa: BLE001
            logger.debug("yjyg %s failed: %s", period, exc)
            continue
        if df is None or df.empty:
            continue
        code_c = _pick_col(df, "股票代码", "代码")
        name_c = _pick_col(df, "股票简称", "名称")
        type_c = _pick_col(df, "预告类型", "业绩预告类型")
        chg_c = _pick_col(df, "预告净利润变动幅度", "净利润变动幅度", "增长幅度")
        for _, r in df.iterrows():
            sym = _code_to_symbol(r.get(code_c) if code_c else None)
            if not sym:
                continue
            name = str(r.get(name_c) or "")
            if _ST.search(name):
                continue
            ftype = str(r.get(type_c) or "") if type_c else ""
            chg = None
            if chg_c is not None:
                raw = r.get(chg_c)
                try:
                    if isinstance(raw, str):
                        m = re.findall(r"-?\d+\.?\d*", raw.replace(",", ""))
                        if m:
                            # take max magnitude positive if range
                            nums = [float(x) for x in m]
                            chg = max(nums)
                    else:
                        chg = float(raw)
                except (TypeError, ValueError):
                    chg = None
            if any(b in ftype for b in _BAD_TYPES):
                continue
            if chg is not None and chg < min_yoy and not any(g in ftype for g in ("预增", "扭亏")):
                continue
            gap = _profit_gap_score(chg, ftype)
            if gap < 1.0:
                continue
            out.append(
                {
                    "symbol": sym,
                    "name": name,
                    "source": "profit_gap",
                    "as_of": period,
                    "board_count": 0,
                    "strong_flag": 0,
                    "amount": 0.0,
                    "profit_gap_score": gap,
                    "event_score": min(2.5, 0.8 + gap * 0.4),
                    "event_tags": ["利润断层", ftype] + ([f"同比{chg:.0f}%"] if chg is not None else []),
                    "thesis": f"业绩预告{period} · {ftype}"
                    + (f" · 同比约{chg:.0f}%" if chg is not None else ""),
                    "forecast_type": ftype,
                    "yoy_pct": chg,
                }
            )
        if out:
            logger.info("Profit-gap forecasts %s: %d names", period, len(out))
            break
    return out


def merge_event_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge multi-source events by symbol; keep strongest board / gap / tags."""
    by: dict[str, dict[str, Any]] = {}
    for r in rows:
        sym = r.get("symbol")
        if not sym:
            continue
        cur = by.get(sym)
        if cur is None:
            by[sym] = {
                **r,
                "sources": [r.get("source")],
                "event_tags": list(r.get("event_tags") or []),
                "theses": [r.get("thesis")] if r.get("thesis") else [],
            }
            continue
        cur["board_count"] = max(int(cur.get("board_count") or 0), int(r.get("board_count") or 0))
        cur["strong_flag"] = max(int(cur.get("strong_flag") or 0), int(r.get("strong_flag") or 0))
        cur["profit_gap_score"] = max(
            float(cur.get("profit_gap_score") or 0), float(r.get("profit_gap_score") or 0)
        )
        cur["event_score"] = max(float(cur.get("event_score") or 0), float(r.get("event_score") or 0))
        cur["amount"] = max(float(cur.get("amount") or 0), float(r.get("amount") or 0))
        if r.get("name") and not cur.get("name"):
            cur["name"] = r["name"]
        src = r.get("source")
        if src and src not in cur["sources"]:
            cur["sources"].append(src)
        for t in r.get("event_tags") or []:
            if t and t not in cur["event_tags"]:
                cur["event_tags"].append(t)
        if r.get("thesis"):
            cur["theses"].append(r["thesis"])
        if r.get("yoy_pct") is not None:
            cur["yoy_pct"] = r.get("yoy_pct")
        if r.get("forecast_type"):
            cur["forecast_type"] = r.get("forecast_type")
    merged = []
    for sym, row in by.items():
        theses = [t for t in (row.get("theses") or []) if t]
        row["thesis"] = " | ".join(theses[:3])
        row["symbol"] = sym
        merged.append(row)
    return merged
