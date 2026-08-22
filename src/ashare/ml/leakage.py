from __future__ import annotations

from typing import Iterable

import pandas as pd


class FutureLeakageError(RuntimeError):
    pass


class LeakageDetector:
    """Hard-fail checks before training."""

    def check_feature_before_label(self, df: pd.DataFrame, feature_cols: Iterable[str]) -> None:
        if "date" not in df.columns or "target" not in df.columns:
            raise FutureLeakageError("dataset missing date/target")
        # features must not include target / future_return / benchmark
        banned = {"target", "future_return", "benchmark_return", "label"}
        bad = [c for c in feature_cols if c in banned]
        if bad:
            raise FutureLeakageError(f"future columns in features: {bad}")
        # if label_asof present, feature date must be < label realization
        if "label_asof" in df.columns and "feature_asof" in df.columns:
            leak = df[pd.to_datetime(df["feature_asof"]) >= pd.to_datetime(df["label_asof"])]
            if len(leak) > 0:
                raise FutureLeakageError(
                    f"feature_asof >= label_asof in {len(leak)} rows — future leakage"
                )

    def check_no_random_split_api(self, split_method: str) -> None:
        if split_method.lower() in {"random", "train_test_split", "shuffle"}:
            raise FutureLeakageError("random train_test_split is forbidden for time series")

    def validate_train_bundle(self, df: pd.DataFrame, feature_cols: list[str], split_method: str) -> None:
        self.check_no_random_split_api(split_method)
        self.check_feature_before_label(df, feature_cols)
