from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterator

import pandas as pd


@dataclass
class TimeFold:
    name: str
    train: pd.DataFrame
    test: pd.DataFrame
    train_end: str
    test_start: str
    test_end: str


def time_split_fixed(
    data: pd.DataFrame,
    train_end: str,
    valid_end: str | None = None,
    test_end: str | None = None,
) -> dict[str, pd.DataFrame]:
    """Explicit calendar splits — never random."""
    d = data.copy()
    d["date"] = pd.to_datetime(d["date"])
    out = {"train": d[d["date"] <= pd.Timestamp(train_end)]}
    if valid_end:
        out["valid"] = d[(d["date"] > pd.Timestamp(train_end)) & (d["date"] <= pd.Timestamp(valid_end))]
    if test_end and valid_end:
        out["test"] = d[(d["date"] > pd.Timestamp(valid_end)) & (d["date"] <= pd.Timestamp(test_end))]
    elif test_end:
        out["test"] = d[(d["date"] > pd.Timestamp(train_end)) & (d["date"] <= pd.Timestamp(test_end))]
    return out


def walk_forward_folds(
    data: pd.DataFrame,
    *,
    train_years: int = 3,
    test_years: int = 1,
    embargos_days: int = 5,
) -> list[TimeFold]:
    if data.empty:
        return []
    d = data.copy()
    d["date"] = pd.to_datetime(d["date"])
    years = sorted({int(ts.year) for ts in d["date"]})
    if len(years) < train_years + test_years:
        # single fold: early / late
        dates = sorted(d["date"].unique())
        cut = dates[int(len(dates) * 0.7)]
        embargo = pd.Timedelta(days=embargos_days)
        train = d[d["date"] <= cut - embargo]
        test = d[d["date"] > cut]
        return [
            TimeFold(
                name="wf_single",
                train=train,
                test=test,
                train_end=str(pd.Timestamp(cut - embargo).date()),
                test_start=str(pd.Timestamp(cut).date()),
                test_end=str(pd.Timestamp(dates[-1]).date()),
            )
        ]

    folds: list[TimeFold] = []
    start_y = years[0]
    end_y = years[-1]
    test_start = start_y + train_years
    while test_start + test_years - 1 <= end_y:
        train_end_y = test_start - 1
        test_end_y = test_start + test_years - 1
        train_end = pd.Timestamp(f"{train_end_y}-12-31")
        test_lo = pd.Timestamp(f"{test_start}-01-01")
        test_hi = pd.Timestamp(f"{test_end_y}-12-31")
        embargo = pd.Timedelta(days=embargos_days)
        train = d[d["date"] <= train_end - embargo]
        test = d[(d["date"] >= test_lo) & (d["date"] <= test_hi)]
        if len(train) >= 50 and len(test) >= 10:
            folds.append(
                TimeFold(
                    name=f"train_{start_y}_{train_end_y}_test_{test_start}_{test_end_y}",
                    train=train,
                    test=test,
                    train_end=str(train_end.date()),
                    test_start=str(test_lo.date()),
                    test_end=str(test_hi.date()),
                )
            )
        test_start += 1
    return folds


def iter_walk_forward(data: pd.DataFrame, **kwargs: Any) -> Iterator[TimeFold]:
    yield from walk_forward_folds(data, **kwargs)
