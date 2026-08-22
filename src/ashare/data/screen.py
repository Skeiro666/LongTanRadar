from __future__ import annotations

import logging
import re
from typing import Any

import pandas as pd

from ashare.symbols import to_symbol

logger = logging.getLogger("ashare.data.screen")

_ST_NAME = re.compile(r"(^|[^\w])ST|退$|退市", re.I)


def _import_ak():
    import akshare as ak  # type: ignore

    return ak


def _norm_spot(df: pd.DataFrame) -> pd.DataFrame:
    rename = {
        "代码": "code",
        "名称": "name",
        "最新价": "price",
        "涨跌幅": "pct_chg",
        "成交量": "volume",
        "成交额": "amount",
    }
    out = df.rename(columns=rename).copy()
    for col in ("price", "pct_chg", "volume", "amount"):
        if col not in out.columns:
            out[col] = 0.0
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0.0)
    out["code"] = out["code"].astype(str).str.strip().str.lower()
    out["name"] = out["name"].astype(str).str.strip()
    return out


def fetch_a_share_spot() -> pd.DataFrame:
    """Full A-share spot snapshot (Sina; Eastmoney fallback)."""
    ak = _import_ak()
    errors: list[str] = []
    for name, loader in (
        ("sina", lambda: ak.stock_zh_a_spot()),
        ("em", lambda: ak.stock_zh_a_spot_em()),
    ):
        try:
            raw = loader()
            if raw is None or raw.empty:
                errors.append(f"{name}:empty")
                continue
            out = _norm_spot(raw)
            logger.info("Spot universe via %s: %d names", name, len(out))
            return out
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{name}:{exc}")
            logger.warning("Spot fetch %s failed: %s", name, exc)
    raise RuntimeError("无法拉取全市场行情: " + "; ".join(errors))


def _to_symbol_from_spot_code(code: str) -> str | None:
    raw = str(code).strip().lower()
    if raw.startswith(("sh", "sz", "bj")) and len(raw) >= 8:
        return to_symbol(f"{raw[2:]}.{raw[:2].upper()}")
    if raw.isdigit() and len(raw) == 6:
        return to_symbol(raw)
    return None


def screen_market(cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """
    Scrape live A-share quotes, apply liquidity/quality filters, return candidates.

    Config under universe.screen:
      min_price, max_price, min_amount, exclude_st, exclude_bj, exclude_cyb,
      max_pct_chg, max_candidates
    """
    uni = (cfg or {}).get("universe", {})
    sc = dict(uni.get("screen") or {})
    min_price = float(sc.get("min_price", 2.0))
    max_price = sc.get("max_price", None)
    max_price_f = float(max_price) if max_price is not None else None
    min_amount = float(sc.get("min_amount", 5.0e7))  # 5千万成交额
    exclude_st = bool(sc.get("exclude_st", True))
    exclude_bj = bool(sc.get("exclude_bj", True))
    exclude_cyb = bool(sc.get("exclude_cyb", False))  # 创业板 300
    exclude_kcb = bool(sc.get("exclude_kcb", True))  # 科创板 688
    max_pct = float(sc.get("max_pct_chg", 9.5))  # 接近涨停不选
    max_daily_gain = sc.get("max_daily_gain", None)
    max_daily_gain_f = float(max_daily_gain) if max_daily_gain is not None else None
    rank_by = str(sc.get("rank_by", "pullback")).lower()  # pullback | liquidity
    max_candidates = int(sc.get("max_candidates", 60))

    spot = fetch_a_share_spot()
    rows: list[dict[str, Any]] = []
    for _, r in spot.iterrows():
        sym = _to_symbol_from_spot_code(r["code"])
        if not sym:
            continue
        code, ex = sym.split(".")
        name = str(r["name"])
        price = float(r["price"])
        amount = float(r["amount"])
        pct = float(r["pct_chg"])
        if price <= 0 or amount <= 0:
            continue
        if exclude_bj and ex == "BJ":
            continue
        if exclude_kcb and code.startswith("688"):
            continue
        if exclude_cyb and code.startswith(("300", "301")):
            continue
        if exclude_st and (_ST_NAME.search(name) or "ST" in name.upper()):
            continue
        if price < min_price:
            continue
        if max_price_f is not None and price > max_price_f:
            continue
        if amount < min_amount:
            continue
        if abs(pct) >= max_pct:
            continue
        if max_daily_gain_f is not None and pct > max_daily_gain_f:
            continue
        rows.append(
            {
                "symbol": sym,
                "name": name,
                "price": price,
                "amount": amount,
                "pct_chg": pct,
            }
        )

    if rank_by == "pullback":
        # 偏回调/横盘，避免按成交额取最热（典型追涨池）
        rows.sort(key=lambda x: (x["pct_chg"], -x["amount"]))
    else:
        rows.sort(key=lambda x: x["amount"], reverse=True)
    picked = rows[:max_candidates]
    logger.info(
        "Market screen: raw=%d filtered=%d candidates=%d rank_by=%s max_daily_gain=%s",
        len(spot),
        len(rows),
        len(picked),
        rank_by,
        max_daily_gain_f,
    )
    return {
        "raw_count": int(len(spot)),
        "filtered_count": int(len(rows)),
        "candidates": picked,
        "symbols": [x["symbol"] for x in picked],
        "filters": {
            "min_price": min_price,
            "max_price": max_price_f,
            "min_amount": min_amount,
            "exclude_st": exclude_st,
            "exclude_bj": exclude_bj,
            "exclude_cyb": exclude_cyb,
            "exclude_kcb": exclude_kcb,
            "max_pct_chg": max_pct,
            "max_daily_gain": max_daily_gain_f,
            "rank_by": rank_by,
            "max_candidates": max_candidates,
        },
    }
