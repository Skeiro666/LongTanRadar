from __future__ import annotations

from typing import Any

import pandas as pd

from ashare.ml.features import FEATURE_COLS, enrich_symbol


def build_dataset(
    panel: dict[str, pd.DataFrame],
    label_horizon: int = 5,
    start: str | None = None,
    end: str | None = None,
) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for sym, df in panel.items():
        if df is None or df.empty:
            continue
        enriched = enrich_symbol(df, label_horizon=label_horizon)
        enriched["symbol"] = sym
        frames.append(enriched)
    if not frames:
        return pd.DataFrame()
    data = pd.concat(frames, ignore_index=True)
    data = data.dropna(subset=FEATURE_COLS + ["label"])
    if start:
        data = data[data["date"] >= pd.Timestamp(start)]
    if end:
        data = data[data["date"] <= pd.Timestamp(end)]
    # Drop ST / halt rows if columns exist
    if "is_st" in data.columns:
        data = data[~data["is_st"].astype(bool)]
    if "is_halt" in data.columns:
        data = data[~data["is_halt"].astype(bool)]
    return data.sort_values(["date", "symbol"]).reset_index(drop=True)


def time_split(
    data: pd.DataFrame,
    valid_ratio: float = 0.2,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if data.empty:
        return data, data
    dates = sorted(data["date"].unique())
    cut = dates[max(0, int(len(dates) * (1.0 - valid_ratio)) - 1)]
    train = data[data["date"] <= cut]
    valid = data[data["date"] > cut]
    if valid.empty and len(dates) > 1:
        cut = dates[-2]
        train = data[data["date"] <= cut]
        valid = data[data["date"] > cut]
    return train.reset_index(drop=True), valid.reset_index(drop=True)


def xy(df: pd.DataFrame) -> tuple[Any, Any]:
    import numpy as np

    x = df[FEATURE_COLS].astype(float).values
    y = df["label"].astype(float).values
    return np.nan_to_num(x, nan=0.0, posinf=0.0, neginf=0.0), y
