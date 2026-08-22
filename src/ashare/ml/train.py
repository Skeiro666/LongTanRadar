from __future__ import annotations

import itertools
import logging
from typing import Any

import lightgbm as lgb
import numpy as np
import pandas as pd

from ashare.data.provider import ensure_panel
from ashare.ml.dataset import build_dataset, time_split, xy
from ashare.ml.features import FEATURE_COLS
from ashare.ml.registry import save_run

logger = logging.getLogger("ashare.ml.train")


def _ic(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    if len(y_true) < 3:
        return 0.0
    corr = pd.Series(y_true).corr(pd.Series(y_pred), method="spearman")
    if corr is None or np.isnan(corr):
        return 0.0
    return float(corr)


def _default_grid(ml: dict[str, Any]) -> list[dict[str, Any]]:
    leaves = ml.get("grid_num_leaves") or [15, 31]
    lrs = ml.get("grid_learning_rate") or [0.05, 0.1]
    mins = ml.get("grid_min_data_in_leaf") or [20, 50]
    grid = []
    for nl, lr, md in itertools.product(leaves, lrs, mins):
        grid.append({"num_leaves": int(nl), "learning_rate": float(lr), "min_data_in_leaf": int(md)})
    return grid


def train_model(
    cfg: dict[str, Any],
    *,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ml = {**cfg.get("ml", {}), **(overrides or {})}
    panel = ensure_panel(cfg)
    if not panel:
        raise RuntimeError("No market data for training")

    label_h = int(ml.get("label_horizon", 5))
    train_start = str(ml.get("train_start", cfg.get("data", {}).get("start", "2021-01-01")))
    train_end = str(ml.get("train_end", cfg.get("backtest", {}).get("end", "2024-12-31")))
    data = build_dataset(panel, label_horizon=label_h, start=train_start, end=train_end)
    if len(data) < 100:
        raise RuntimeError(f"Not enough training rows: {len(data)}")

    train_df, valid_df = time_split(data, valid_ratio=float(ml.get("valid_ratio", 0.2)))
    x_tr, y_tr = xy(train_df)
    x_va, y_va = xy(valid_df)
    if len(x_va) < 10:
        x_va, y_va = x_tr[-50:], y_tr[-50:]

    grid = _default_grid(ml)
    # Single override from UI
    if overrides and any(k in overrides for k in ("num_leaves", "learning_rate", "min_data_in_leaf")):
        grid = [
            {
                "num_leaves": int(overrides.get("num_leaves", 31)),
                "learning_rate": float(overrides.get("learning_rate", 0.05)),
                "min_data_in_leaf": int(overrides.get("min_data_in_leaf", 20)),
            }
        ]

    best: dict[str, Any] | None = None
    best_model = None
    for params in grid:
        booster = lgb.LGBMRegressor(
            objective="regression",
            n_estimators=int(ml.get("n_estimators", 120)),
            num_leaves=params["num_leaves"],
            learning_rate=params["learning_rate"],
            min_child_samples=params["min_data_in_leaf"],
            subsample=0.8,
            colsample_bytree=0.8,
            random_state=42,
            verbosity=-1,
        )
        booster.fit(x_tr, y_tr, eval_X=x_va, eval_y=y_va)
        pred = booster.predict(x_va)
        ic = _ic(y_va, pred)
        mse = float(np.mean((y_va - pred) ** 2))
        logger.info("params=%s IC=%.4f MSE=%.6f", params, ic, mse)
        score = ic - mse  # prefer higher IC
        if best is None or score > best["score"]:
            imp = dict(zip(FEATURE_COLS, [float(x) for x in booster.feature_importances_]))
            best = {
                "params": params,
                "ic": ic,
                "mse": mse,
                "score": score,
                "feature_importance": imp,
                "n_train": int(len(x_tr)),
                "n_valid": int(len(x_va)),
                "label_horizon": label_h,
                "train_start": train_start,
                "train_end": train_end,
                "feature_cols": FEATURE_COLS,
            }
            best_model = booster

    if best_model is None or best is None:
        raise RuntimeError("Training failed")

    meta = save_run(cfg, best_model, best)
    return meta
