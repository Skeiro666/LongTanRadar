from __future__ import annotations

import logging
import time
from typing import Any

import pandas as pd
import requests

from ashare.symbols import bare_code, board_limit_pct, to_symbol

logger = logging.getLogger("ashare.data.akshare")


def _import_ak():
    import akshare as ak  # type: ignore

    return ak


def _sina_code(symbol: str) -> str:
    sym = to_symbol(symbol)
    code, ex = sym.split(".")
    return f"{ex.lower()}{code}"


def fetch_hs300_constituents() -> list[str]:
    ak = _import_ak()
    df = ak.index_stock_cons_csindex(symbol="000300")
    col = "成分券代码" if "成分券代码" in df.columns else df.columns[0]
    return [to_symbol(str(x)) for x in df[col].tolist()]


def fetch_st_codes() -> set[str]:
    ak = _import_ak()
    try:
        df = ak.stock_zh_a_st_em()
    except Exception as exc:  # noqa: BLE001
        logger.warning("ST list fetch failed: %s", exc)
        return set()
    code_col = "代码" if "代码" in df.columns else df.columns[0]
    return {to_symbol(str(x)) for x in df[code_col].tolist()}


def _normalize_bars(df: pd.DataFrame, symbol: str, st_codes: set[str] | None) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()

    rename = {
        "日期": "date",
        "开盘": "open",
        "收盘": "close",
        "最高": "high",
        "最低": "low",
        "成交量": "volume",
        "成交额": "amount",
        "涨跌幅": "pct_chg",
    }
    out = df.rename(columns=rename).copy()
    out["date"] = pd.to_datetime(out["date"])
    out["symbol"] = to_symbol(symbol)
    for col in ("open", "high", "low", "close", "volume", "amount"):
        if col not in out.columns:
            out[col] = 0.0
        out[col] = pd.to_numeric(out[col], errors="coerce")
    if "pct_chg" not in out.columns:
        prev = out["close"].shift(1)
        out["pct_chg"] = ((out["close"] / prev) - 1.0) * 100.0
    out["pct_chg"] = pd.to_numeric(out["pct_chg"], errors="coerce").fillna(0.0)

    is_st = to_symbol(symbol) in (st_codes or set())
    out["is_st"] = is_st
    out["is_halt"] = out["volume"].fillna(0) <= 0
    lim = board_limit_pct(symbol, is_st=is_st)
    pct = out["pct_chg"]
    out["limit_up"] = (~out["is_halt"]) & (pct >= (lim - 0.05))
    out["limit_down"] = (~out["is_halt"]) & (pct <= -(lim - 0.05))
    keep = [
        "date",
        "symbol",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
        "pct_chg",
        "is_st",
        "is_halt",
        "limit_up",
        "limit_down",
    ]
    return out[keep].dropna(subset=["close"]).sort_values("date").reset_index(drop=True)


def _fetch_em_hist(ak: Any, code: str, start_s: str, end_s: str) -> pd.DataFrame:
    return ak.stock_zh_a_hist(
        symbol=code,
        period="daily",
        start_date=start_s,
        end_date=end_s,
        adjust="qfq",
    )


def _fetch_sina_daily(ak: Any, symbol: str, start_s: str, end_s: str) -> pd.DataFrame:
    return ak.stock_zh_a_daily(
        symbol=_sina_code(symbol),
        start_date=start_s,
        end_date=end_s,
        adjust="qfq",
    )


def _fetch_tx_hist(ak: Any, symbol: str, start: str, end: str) -> pd.DataFrame:
    return ak.stock_zh_a_hist_tx(
        symbol=_sina_code(symbol),
        start_date=start,
        end_date=end,
        adjust="qfq",
    )


def fetch_daily(symbol: str, start: str, end: str, st_codes: set[str] | None = None) -> pd.DataFrame:
    """Forward-adjusted daily bars + actual pct_chg for limit/halt flags.

    Tries Eastmoney first, then Sina daily / Tencent hist (EM often drops connections).
    """
    ak = _import_ak()
    code = bare_code(symbol)
    start_s = start.replace("-", "")
    end_s = end.replace("-", "")
    errors: list[str] = []

    for name, loader in (
        ("em", lambda: _fetch_em_hist(ak, code, start_s, end_s)),
        ("sina", lambda: _fetch_sina_daily(ak, symbol, start_s, end_s)),
        ("tx", lambda: _fetch_tx_hist(ak, symbol, start, end)),
    ):
        try:
            raw = loader()
            normalized = _normalize_bars(raw, symbol, st_codes)
            if not normalized.empty:
                if name != "em":
                    logger.info("Using %s bars for %s", name, to_symbol(symbol))
                return normalized
            errors.append(f"{name}:empty")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{name}:{exc}")
            logger.debug("Fetch %s via %s failed: %s", symbol, name, exc)

    logger.warning("All hist sources failed for %s (%s)", symbol, "; ".join(errors))
    return pd.DataFrame()


def fetch_spot_prices(symbols: list[str]) -> dict[str, float]:
    """Latest trade price via Sina HQ (batch)."""
    codes = [to_symbol(s) for s in symbols]
    if not codes:
        return {}
    url = "https://hq.sinajs.cn/list=" + ",".join(_sina_code(s) for s in codes)
    try:
        resp = requests.get(
            url,
            headers={"Referer": "https://finance.sina.com.cn", "User-Agent": "Mozilla/5.0"},
            timeout=10,
        )
        resp.encoding = "gbk"
        text = resp.text
    except Exception as exc:  # noqa: BLE001
        logger.warning("Sina spot fetch failed: %s", exc)
        return {}

    out: dict[str, float] = {}
    for line in text.splitlines():
        # var hq_str_sh601166="兴业银行,open,...,price,..."
        if "hq_str_" not in line or "=" not in line:
            continue
        left, _, right = line.partition("=")
        key = left.split("_")[-1].strip()
        payload = right.strip().strip(";").strip('"')
        if not payload:
            continue
        parts = payload.split(",")
        if len(parts) < 4:
            continue
        try:
            px = float(parts[3])
        except ValueError:
            continue
        if px <= 0:
            continue
        # key like sh601166
        if len(key) >= 8:
            ex, num = key[:2].upper(), key[2:]
            out[f"{num}.{ex}"] = px
    return out


def fetch_many(
    symbols: list[str],
    start: str,
    end: str,
    sleep_sec: float = 0.2,
) -> dict[str, pd.DataFrame]:
    st_codes = fetch_st_codes()
    out: dict[str, pd.DataFrame] = {}
    for i, raw in enumerate(symbols):
        sym = to_symbol(raw)
        try:
            df = fetch_daily(sym, start, end, st_codes=st_codes)
            if not df.empty:
                out[sym] = df
                logger.info("Fetched %s rows=%d last=%.4f", sym, len(df), float(df.iloc[-1]["close"]))
            else:
                logger.warning("Empty bars for %s", sym)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Fetch failed %s: %s", sym, exc)
        if i + 1 < len(symbols):
            time.sleep(sleep_sec)
    return out
