from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from ashare.symbols import bare_code, board_limit_pct, to_symbol

logger = logging.getLogger("ashare.data.akshare")

_ST_CACHE_TTL_SEC = 86400
_ST_MEM: tuple[float, set[str]] | None = None


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _st_cache_path() -> Path:
    return _project_root() / "data" / "cache" / "st_codes.json"


def _load_st_cache(*, allow_stale: bool = False) -> set[str] | None:
    path = _st_cache_path()
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        codes = {to_symbol(str(x)) for x in (payload.get("codes") or [])}
        updated = float(payload.get("updated_at") or 0)
        age = time.time() - updated
        if codes and (allow_stale or age <= _ST_CACHE_TTL_SEC):
            return codes
    except Exception as exc:  # noqa: BLE001
        logger.debug("ST cache read failed: %s", exc)
    return None


def _save_st_cache(codes: set[str]) -> None:
    path = _st_cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {"updated_at": time.time(), "n": len(codes), "codes": sorted(codes)},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


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


def fetch_st_codes(*, max_retries: int = 3) -> set[str]:
    """Fetch A-share ST symbols from Eastmoney; retry + file cache on network blips."""
    global _ST_MEM
    now = time.time()
    if _ST_MEM and now - _ST_MEM[0] < 300:
        return _ST_MEM[1]

    fresh = _load_st_cache(allow_stale=False)
    if fresh is not None:
        _ST_MEM = (now, fresh)
        return fresh

    ak = _import_ak()
    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            df = ak.stock_zh_a_st_em()
            code_col = "代码" if "代码" in df.columns else df.columns[0]
            codes = {to_symbol(str(x)) for x in df[code_col].tolist()}
            if codes:
                _save_st_cache(codes)
                _ST_MEM = (now, codes)
                logger.info("ST list fetched: n=%d", len(codes))
                return codes
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt + 1 < max_retries:
                time.sleep(0.6 * (attempt + 1))
                logger.debug("ST list fetch retry %d/%d: %s", attempt + 2, max_retries, exc)

    stale = _load_st_cache(allow_stale=True)
    if stale:
        _ST_MEM = (now, stale)
        logger.warning(
            "ST list fetch failed (%s); using cached ST list (n=%d)",
            last_exc,
            len(stale),
        )
        return stale

    logger.warning(
        "ST list fetch failed (%s); no ST cache — is_st/limit flags may be incomplete this run",
        last_exc,
    )
    return set()


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


def fetch_spot_quotes(symbols: list[str]) -> dict[str, dict[str, Any]]:
    """Batch Sina HQ quotes: price / prev_close / open / high / low / name.

    Does not mutate research or daily caches — live overlay only.
    """
    codes = [to_symbol(s) for s in symbols]
    if not codes:
        return {}
    # Sina list URL length is finite; chunk to stay safe with large Focus sets.
    chunk_size = 80
    out: dict[str, dict[str, Any]] = {}
    headers = {"Referer": "https://finance.sina.com.cn", "User-Agent": "Mozilla/5.0"}
    for i in range(0, len(codes), chunk_size):
        batch = codes[i : i + chunk_size]
        url = "https://hq.sinajs.cn/list=" + ",".join(_sina_code(s) for s in batch)
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            resp.encoding = "gbk"
            text = resp.text
        except Exception as exc:  # noqa: BLE001
            logger.warning("Sina spot fetch failed: %s", exc)
            continue

        for line in text.splitlines():
            # var hq_str_sh601166="兴业银行,open,prev_close,price,high,low,..."
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
                open_px = float(parts[1]) if parts[1] else 0.0
                prev_close = float(parts[2]) if parts[2] else 0.0
                px = float(parts[3])
                high = float(parts[4]) if len(parts) > 4 and parts[4] else 0.0
                low = float(parts[5]) if len(parts) > 5 and parts[5] else 0.0
            except ValueError:
                continue
            if px <= 0:
                continue
            if len(key) < 8:
                continue
            ex, num = key[:2].upper(), key[2:]
            sym = f"{num}.{ex}"
            name = str(parts[0] or "").strip()
            change_pct = None
            if prev_close > 0:
                change_pct = ((px / prev_close) - 1.0) * 100.0
            out[sym] = {
                "symbol": sym,
                "name": name,
                "price": px,
                "prev_close": prev_close,
                "open": open_px,
                "high": high,
                "low": low,
                "change_pct": change_pct,
                "is_st": ("ST" in name.upper()) if name else False,
            }
    return out


def fetch_spot_prices(symbols: list[str]) -> dict[str, float]:
    """Latest trade price via Sina HQ (batch). Compatible wrapper over fetch_spot_quotes."""
    quotes = fetch_spot_quotes(symbols)
    return {sym: float(q["price"]) for sym, q in quotes.items() if float(q.get("price") or 0) > 0}


CSI300_INDEX_SYMBOL = "IDX.CSI300"


def fetch_csi300_index_bars(cfg: dict[str, Any] | None = None) -> pd.DataFrame:
    """Fetch CSI300 (000300) daily index bars; cache under data/cache/daily."""
    from ashare.data.store import ParquetStore

    cfg = cfg or {}
    root = Path(cfg.get("_root") or Path(__file__).resolve().parents[3])
    cache_dir = (cfg.get("data") or {}).get("cache_dir") or "data/cache"
    store = ParquetStore(root / cache_dir)
    cached = store.load_daily(CSI300_INDEX_SYMBOL)
    try:
        ak = _import_ak()
        raw = ak.stock_zh_index_daily(symbol="sh000300")
    except Exception as exc:  # noqa: BLE001
        logger.warning("CSI300 index fetch failed: %s", exc)
        return cached if cached is not None else pd.DataFrame()

    if raw is None or raw.empty:
        return cached if cached is not None else pd.DataFrame()

    out = raw.copy()
    if "date" not in out.columns and "日期" in out.columns:
        out = out.rename(columns={"日期": "date"})
    out["date"] = pd.to_datetime(out["date"])
    for src, dst in (("open", "open"), ("high", "high"), ("low", "low"), ("close", "close"), ("volume", "volume")):
        if dst not in out.columns:
            cn = {"open": "开盘", "high": "最高", "low": "最低", "close": "收盘", "volume": "成交量"}.get(dst)
            if cn in out.columns:
                out[dst] = out[cn]
    out["symbol"] = CSI300_INDEX_SYMBOL
    out["amount"] = 0.0
    out["pct_chg"] = out["close"].pct_change().fillna(0.0) * 100.0
    out["is_st"] = False
    out["is_halt"] = False
    out["limit_up"] = False
    out["limit_down"] = False
    out = out.sort_values("date").drop_duplicates(subset=["date"]).reset_index(drop=True)
    try:
        store.save_daily(CSI300_INDEX_SYMBOL, out)
    except Exception as exc:  # noqa: BLE001
        logger.warning("CSI300 cache save failed: %s", exc)
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
