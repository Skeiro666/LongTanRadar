from __future__ import annotations

import itertools
import logging
from typing import Any

import lightgbm as lgb
import numpy as np
import pandas as pd

from ashare.config_loaders import load_yaml_config
from ashare.factors.engine import FactorEngine
from ashare.ml.leakage import LeakageDetector
from ashare.ml.registry import save_run
from ashare.ml.target import attach_excess_target
from ashare.ml.walk_forward import walk_forward_folds

logger = logging.getLogger("ashare.ml.ranking")


def _spearman_ic(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    if len(y_true) < 3:
        return 0.0
    corr = pd.Series(y_true).corr(pd.Series(y_pred), method="spearman")
    if corr is None or np.isnan(corr):
        return 0.0
    return float(corr)


class MLRankingEngine:
    """LightGBM as candidate ranker predicting excess return — not a trade trigger."""

    def __init__(self, cfg: dict[str, Any] | None = None) -> None:
        self.cfg = cfg or {}
        self.models_cfg = load_yaml_config(self.cfg, "models")
        self.lgbm_cfg = dict(self.models_cfg.get("lgbm") or {})
        self.factor_engine = FactorEngine(self.cfg)
        self.detector = LeakageDetector()
        self.feature_cols: list[str] = []
        self.model: Any | None = None
        self.meta: dict[str, Any] = {}

    def build_training_frame(self, panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
        raw = self.factor_engine.compute_panel(panel)
        if raw.empty:
            return raw
        horizon = int(self.lgbm_cfg.get("prediction_horizon_days", 5))
        data = attach_excess_target(
            raw,
            horizon=horizon,
            benchmark=str(self.lgbm_cfg.get("benchmark") or "equal_weight_universe"),
        )
        self.feature_cols = [
            c
            for c in self.factor_engine.catalog.available_names()
            if c in data.columns
        ]
        # drop rows without target or all-nan features
        data = data.dropna(subset=["target"])
        return data

    def train(self, panel: dict[str, pd.DataFrame]) -> dict[str, Any]:
        data = self.build_training_frame(panel)
        if len(data) < 100:
            raise RuntimeError(f"Not enough ranking rows: {len(data)}")
        self.detector.validate_train_bundle(data, self.feature_cols, split_method="walk_forward")

        wf = dict(self.lgbm_cfg.get("walk_forward") or {})
        folds = walk_forward_folds(
            data,
            train_years=int(wf.get("train_years", 3)),
            test_years=int(wf.get("test_years", 1)),
            embargos_days=int(wf.get("embargos_days", 5)),
        )
        oos_ics: list[float] = []
        last_model = None
        last_imp: dict[str, float] = {}
        for fold in folds:
            x_tr = np.nan_to_num(fold.train[self.feature_cols].astype(float).values)
            y_tr = fold.train["target"].astype(float).values
            x_te = np.nan_to_num(fold.test[self.feature_cols].astype(float).values)
            y_te = fold.test["target"].astype(float).values
            model = self._fit_one(x_tr, y_tr, x_te, y_te)
            pred = model.predict(x_te)
            ic = _spearman_ic(y_te, pred)
            oos_ics.append(ic)
            last_model = model
            last_imp = dict(zip(self.feature_cols, [float(x) for x in model.feature_importances_]))
            logger.info("walk-forward %s OOS IC=%.4f n_test=%d", fold.name, ic, len(y_te))

        self.model = last_model
        self.meta = {
            "model_version": self.lgbm_cfg.get("model_version", "lgbm_v1"),
            "target": "excess_return",
            "horizon": int(self.lgbm_cfg.get("prediction_horizon_days", 5)),
            "feature_cols": self.feature_cols,
            "oos_ic_mean": float(np.mean(oos_ics) if oos_ics else 0.0),
            "oos_ic_folds": oos_ics,
            "feature_importance": last_imp,
            "n_folds": len(folds),
            "split_method": "walk_forward",
            "value_available": False,
            "quality_available": False,
        }
        if last_model is not None:
            try:
                save_run(self.cfg, last_model, {**self.meta, "ic": self.meta["oos_ic_mean"], "params": {}})
            except Exception as exc:  # noqa: BLE001
                logger.warning("save ranking model failed: %s", exc)
        return self.meta

    def _fit_one(self, x_tr, y_tr, x_va, y_va):
        grid = self.lgbm_cfg.get("grid") or {}
        leaves = grid.get("num_leaves") or [31]
        lrs = grid.get("learning_rate") or [0.05]
        mins = grid.get("min_data_in_leaf") or [20]
        best = None
        best_score = -1e9
        for nl, lr, md in itertools.product(leaves, lrs, mins):
            booster = lgb.LGBMRegressor(
                objective="regression",
                n_estimators=int(self.lgbm_cfg.get("n_estimators", 120)),
                num_leaves=int(nl),
                learning_rate=float(lr),
                min_child_samples=int(md),
                subsample=0.8,
                colsample_bytree=0.8,
                random_state=42,
                verbosity=-1,
            )
            booster.fit(x_tr, y_tr, eval_set=[(x_va, y_va)])
            pred = booster.predict(x_va)
            ic = _spearman_ic(y_va, pred)
            if ic > best_score:
                best_score = ic
                best = booster
        return best

    def predict_rows(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        from ashare.ml.registry import load_model

        model = self.model or load_model(self.cfg)
        if model is None:
            for r in rows:
                r = dict(r)
                r["ml_prediction"] = None
                r["ml_status"] = "no_model"
            return rows
        feats = self.feature_cols or list(getattr(model, "feature_name_", []) or [])
        if not feats:
            feats = self.factor_engine.catalog.available_names()
        out = []
        for r in rows:
            fdict = r.get("factors") or {}
            x = np.array([[float(fdict.get(c) or 0.0) for c in feats]], dtype=float)
            x = np.nan_to_num(x, nan=0.0, posinf=0.0, neginf=0.0)
            try:
                pred = float(model.predict(x)[0])
            except Exception:  # noqa: BLE001
                pred = 0.0
            item = dict(r)
            item["ml_prediction"] = pred
            item["ml_status"] = "ok"
            out.append(item)
        return out
