from __future__ import annotations

from pathlib import Path

import pandas as pd

DAILY_COLS = [
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


class ParquetStore:
    def __init__(self, cache_dir: str | Path) -> None:
        self.root = Path(cache_dir)
        self.daily_dir = self.root / "daily"
        self.daily_dir.mkdir(parents=True, exist_ok=True)

    def daily_path(self, symbol: str) -> Path:
        return self.daily_dir / f"{symbol.replace('.', '_')}.parquet"

    def save_daily(self, symbol: str, df: pd.DataFrame) -> Path:
        path = self.daily_path(symbol)
        out = df.copy()
        out["date"] = pd.to_datetime(out["date"]).dt.strftime("%Y-%m-%d")
        for col in DAILY_COLS:
            if col not in out.columns:
                out[col] = False if col.startswith("is_") or col.startswith("limit_") else 0
        out = out[DAILY_COLS].drop_duplicates(subset=["date"]).sort_values("date")
        out.to_parquet(path, index=False)
        return path

    def load_daily(self, symbol: str) -> pd.DataFrame | None:
        path = self.daily_path(symbol)
        if not path.exists():
            return None
        df = pd.read_parquet(path)
        df["date"] = pd.to_datetime(df["date"])
        return df.sort_values("date").reset_index(drop=True)

    def load_panel(self, symbols: list[str]) -> dict[str, pd.DataFrame]:
        panel: dict[str, pd.DataFrame] = {}
        for sym in symbols:
            df = self.load_daily(sym)
            if df is not None and not df.empty:
                panel[sym] = df
        return panel

    def has_any(self, symbols: list[str]) -> bool:
        return any(self.daily_path(s).exists() for s in symbols)
