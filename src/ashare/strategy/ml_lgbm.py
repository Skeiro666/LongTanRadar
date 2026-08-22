from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import joblib
import numpy as np

from ashare.ml.features import FEATURE_COLS, feature_row_from_closes
from ashare.models import OrderIntent
from ashare.strategy.base import Strategy, StrategyContext, intents_from_weights
from ashare.symbols import to_symbol

logger = logging.getLogger("ashare.strategy.ml_lgbm")


class MLLgbmStrategy(Strategy):
    """Month-end Top-N by LightGBM predicted forward return."""

    def __init__(
        self,
        cfg: dict[str, Any],
        top_n: int = 5,
        max_name_weight: float = 0.20,
        max_gross_weight: float = 0.95,
        rebalance_threshold: float = 0.05,
        model_path: str | None = None,
        run_id: str | None = None,
    ) -> None:
        self.cfg = cfg
        self.top_n = int(top_n)
        self.max_name_weight = float(max_name_weight)
        self.max_gross_weight = float(max_gross_weight)
        self.rebalance_threshold = float(rebalance_threshold)
        self.model_path = model_path
        self.run_id = run_id
        self._model = None

    def _ensure_model(self) -> Any | None:
        if self._model is not None:
            return self._model
        from ashare.ml.registry import load_model, resolve_model_path

        if self.model_path:
            p = Path(self.model_path)
            if not p.is_absolute():
                p = Path(self.cfg["_root"]) / p
            if p.exists():
                self._model = joblib.load(p)
                return self._model
        self._model = load_model(self.cfg, run_id=self.run_id)
        if self._model is None:
            path = resolve_model_path(self.cfg, run_id=self.run_id)
            logger.warning("No LightGBM model found at %s", path)
        return self._model

    def on_date(self, ctx: StrategyContext) -> list[OrderIntent]:
        ctx.rebalance_threshold = self.rebalance_threshold
        if not ctx.is_month_end:
            return []
        model = self._ensure_model()
        if model is None:
            return intents_from_weights(ctx, {}, reason="ml_lgbm_no_model")

        scores: dict[str, float] = {}
        for sym in ctx.tradable():
            hist = ctx.history.get(to_symbol(sym))
            if hist is None or hist.empty:
                continue
            hist = hist.sort_values("date")
            closes = hist.set_index("date")["close"].astype(float)
            vols = hist.set_index("date")["volume"].astype(float) if "volume" in hist.columns else None
            highs = hist.set_index("date")["high"].astype(float) if "high" in hist.columns else None
            lows = hist.set_index("date")["low"].astype(float) if "low" in hist.columns else None
            feats = feature_row_from_closes(closes, vols, highs, lows)
            if feats is None:
                continue
            x = np.array([[feats[c] for c in FEATURE_COLS]], dtype=float)
            x = np.nan_to_num(x, nan=0.0, posinf=0.0, neginf=0.0)
            scores[sym] = float(model.predict(x)[0])

        if not scores:
            return intents_from_weights(ctx, {}, reason="ml_lgbm_empty")
        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        picked = [s for s, _ in ranked[: self.top_n]]
        raw = 1.0 / len(picked)
        w = min(raw, self.max_name_weight)
        weights = {s: w for s in picked}
        gross = sum(weights.values())
        if gross > self.max_gross_weight:
            scale = self.max_gross_weight / gross
            weights = {k: v * scale for k, v in weights.items()}
        return intents_from_weights(ctx, weights, reason="ml_lgbm")
