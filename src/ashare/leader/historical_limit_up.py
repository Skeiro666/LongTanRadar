"""Historical limit-up universe from daily bars + optional AkShare zt-pool cache."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pandas as pd

from ashare.pool.events import _code_to_symbol, _pick_col, _ST

logger = logging.getLogger("ashare.leader.historical_limit_up")


def limit_up_universe_from_bars(df: pd.DataFrame, *, as_of: str) -> bool:
    """True if symbol limit-up on as_of using bars only (as-of)."""
    if df is None or df.empty or "limit_up" not in df.columns:
        return False
    frame = df.copy()
    frame["date"] = pd.to_datetime(frame["date"])
    cut = pd.Timestamp(as_of).normalize()
    day = frame[frame["date"].dt.normalize() == cut]
    if day.empty:
        return False
    return bool(day.iloc[-1]["limit_up"])


def rebuild_daily_limit_up_index(cache_dir: Path, *, out_path: Path, max_symbols: int | None = None) -> dict[str, Any]:
    """
    Rebuild {YYYY-MM-DD: [symbols]} from cached daily bars' limit_up flag.
    This is the as-of historical limit-up universe for symbols we have — not today's pool backfilled.
    """
    paths = sorted(p for p in cache_dir.glob("*.parquet") if not p.stem.startswith("IDX"))
    if max_symbols:
        paths = paths[:max_symbols]
    by_date: dict[str, list[str]] = {}
    n_rows = 0
    for p in paths:
        sym = p.stem.replace("_", ".")
        try:
            df = pd.read_parquet(p, columns=["date", "limit_up"])
        except Exception:  # noqa: BLE001
            df = pd.read_parquet(p)
        if "limit_up" not in df.columns:
            continue
        df["date"] = pd.to_datetime(df["date"])
        lu = df[df["limit_up"].astype(bool)]
        for d in lu["date"].dt.normalize().unique():
            key = str(pd.Timestamp(d).date())
            by_date.setdefault(key, []).append(sym)
            n_rows += 1
    out_path.parent.mkdir(parents=True, exist_ok=True)
    meta = {
        "n_symbols": len(paths),
        "n_dates": len(by_date),
        "n_limit_up_rows": n_rows,
        "date_start": min(by_date) if by_date else None,
        "date_end": max(by_date) if by_date else None,
        "source": "daily_bars.limit_up",
        "note": "Rebuilt from as-of bars; not backfilled from today's zt pool.",
    }
    payload = {"meta": meta, "by_date": {k: sorted(set(v)) for k, v in sorted(by_date.items())}}
    out_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return meta


def fetch_and_cache_zt_pool_day(date_yyyymmdd: str, cache_dir: Path) -> list[dict[str, Any]]:
    """Fetch one day EM zt pool; cache under leader_history/zt_pool/YYYY/MM/DD.json."""
    y, m, d = date_yyyymmdd[:4], date_yyyymmdd[4:6], date_yyyymmdd[6:8]
    path = cache_dir / y / m / f"{d}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    try:
        import akshare as ak  # type: ignore

        df = ak.stock_zt_pool_em(date=date_yyyymmdd)
    except Exception as exc:  # noqa: BLE001
        logger.debug("zt pool %s failed: %s", date_yyyymmdd, exc)
        return []
    if df is None or df.empty:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("[]", encoding="utf-8")
        return []
    code_c = _pick_col(df, "代码", "股票代码")
    name_c = _pick_col(df, "名称", "股票名称")
    board_c = _pick_col(df, "连板数", "连板")
    out: list[dict[str, Any]] = []
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
        out.append({"symbol": sym, "name": name, "board_count": max(1, boards), "as_of": date_yyyymmdd})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return out
