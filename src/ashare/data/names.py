from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from ashare.symbols import bare_code, to_symbol

logger = logging.getLogger("ashare.data.names")

# Offline fallback for common names (watchlist + samples)
STATIC_NAMES: dict[str, str] = {
    "601288.SH": "农业银行",
    "601398.SH": "工商银行",
    "601988.SH": "中国银行",
    "601328.SH": "交通银行",
    "600016.SH": "民生银行",
    "000001.SZ": "平安银行",
    "601166.SH": "兴业银行",
    "601818.SH": "光大银行",
    "600919.SH": "江苏银行",
    "002142.SZ": "宁波银行",
    "600519.SH": "贵州茅台",
    "000858.SZ": "五粮液",
    "601318.SH": "中国平安",
    "600036.SH": "招商银行",
    "000333.SZ": "美的集团",
    "600276.SH": "恒瑞医药",
    "002415.SZ": "海康威视",
    "600900.SH": "长江电力",
    "601888.SH": "中国中免",
    "000651.SZ": "格力电器",
}


def _cache_path(cfg: dict[str, Any] | None = None) -> Path:
    root = Path((cfg or {}).get("_root", "."))
    cache = Path((cfg or {}).get("data", {}).get("cache_dir", "data/cache"))
    if not cache.is_absolute():
        cache = root / cache
    cache.mkdir(parents=True, exist_ok=True)
    return cache / "stock_names.json"


def load_name_map(cfg: dict[str, Any] | None = None) -> dict[str, str]:
    path = _cache_path(cfg)
    names = dict(STATIC_NAMES)
    if path.exists():
        try:
            names.update({to_symbol(k): str(v) for k, v in json.loads(path.read_text(encoding="utf-8")).items()})
        except Exception as exc:  # noqa: BLE001
            logger.warning("load name cache failed: %s", exc)
    return names


def save_name_map(cfg: dict[str, Any], names: dict[str, str]) -> None:
    path = _cache_path(cfg)
    path.write_text(json.dumps(names, ensure_ascii=False, indent=2), encoding="utf-8")


def refresh_names_from_akshare(cfg: dict[str, Any], symbols: list[str] | None = None) -> dict[str, str]:
    """Fetch A-share code→name via AkShare; merge into cache."""
    names = load_name_map(cfg)
    try:
        import akshare as ak

        df = ak.stock_info_a_code_name()
    except Exception as exc:  # noqa: BLE001
        logger.warning("AkShare name list failed: %s", exc)
        return names

    code_col = "code" if "code" in df.columns else df.columns[0]
    name_col = "name" if "name" in df.columns else df.columns[1]
    wanted = {bare_code(s) for s in symbols} if symbols else None
    for _, row in df.iterrows():
        code = str(row[code_col]).zfill(6)
        if wanted is not None and code not in wanted:
            continue
        sym = to_symbol(code)
        names[sym] = str(row[name_col]).strip()
    save_name_map(cfg, names)
    return names


def name_of(symbol: str, cfg: dict[str, Any] | None = None, names: dict[str, str] | None = None) -> str:
    sym = to_symbol(symbol)
    table = names if names is not None else load_name_map(cfg)
    return table.get(sym) or STATIC_NAMES.get(sym) or ""


def attach_names(rows: list[dict[str, Any]], cfg: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    table = load_name_map(cfg)
    missing = [r["symbol"] for r in rows if r.get("symbol") and not table.get(to_symbol(r["symbol"]))]
    if missing and cfg is not None:
        table = refresh_names_from_akshare(cfg, missing)
    out = []
    for r in rows:
        item = dict(r)
        sym = to_symbol(str(item.get("symbol", "")))
        item["symbol"] = sym
        item["name"] = table.get(sym) or STATIC_NAMES.get(sym) or sym
        out.append(item)
    return out
