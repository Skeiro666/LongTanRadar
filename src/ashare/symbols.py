from __future__ import annotations

import re

_EX_SH = re.compile(r"^(6\d{5}|900\d{3})$")  # 沪A 6xxxxx；沪B 900xxx
_EX_SZ = re.compile(r"^(0|1|2|3)\d{5}$")
_EX_BJ = re.compile(r"^(4|8)\d{5}$|^92\d{4}$")  # 北交所 4/8xxxxx、92xxxx


def to_symbol(code: str) -> str:
    """Normalize to 000001.SZ / 600000.SH / 830001.BJ / 920809.BJ."""
    raw = str(code).strip().upper().replace("SHSE.", "").replace("SZSE.", "")
    if "." in raw:
        num, ex = raw.split(".", 1)
        num = num.zfill(6)
        ex = {"SS": "SH", "XSHG": "SH", "XSHE": "SZ", "SZ": "SZ", "SH": "SH", "BJ": "BJ"}.get(ex, ex)
        # 纠偏：92xxxx 即使被标成 .SH 也归北交所
        if num.startswith("92"):
            ex = "BJ"
        return f"{num}.{ex}"
    num = raw.zfill(6)
    if _EX_BJ.match(num):
        return f"{num}.BJ"
    if _EX_SH.match(num):
        return f"{num}.SH"
    if _EX_SZ.match(num):
        return f"{num}.SZ"
    return f"{num}.SZ"


def bare_code(symbol: str) -> str:
    return to_symbol(symbol).split(".")[0]


def board_limit_pct(symbol: str, is_st: bool = False, as_of: str | None = None) -> float:
    """Daily limit percent (absolute)."""
    if is_st:
        return 5.0
    sym = to_symbol(symbol)
    code, ex = sym.split(".")
    if ex == "BJ" or code.startswith(("8", "4")):
        return 30.0
    if code.startswith("688"):
        return 20.0
    if code.startswith("300") or code.startswith("301"):
        # ChiNext 20% since 2020-08-24
        if as_of and as_of < "2020-08-24":
            return 10.0
        return 20.0
    return 10.0


def round_lot(shares: int, lot_size: int = 100) -> int:
    if shares <= 0:
        return 0
    return (shares // lot_size) * lot_size
