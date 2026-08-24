from __future__ import annotations

"""Optional Exit LightGBM — only trains when sample >= minimum. Else available=false."""

from pathlib import Path
from typing import Any

from ashare.portfolio.exit.config import load_exit_config, soft_action


FEATURE_KEYS = [
    "trend_decay",
    "momentum_decay",
    "relative_strength_decay",
    "volume_distribution",
    "price_extension",
    "drawdown",
    "volatility",
    "breakout_failure",
    "moving_average_break",
    "news_reversal",
    "event_completion",
    "time_in_position",
    "profit_loss",
    "portfolio_concentration",
]


def _model_path(cfg: dict[str, Any] | None) -> Path:
    root = Path((cfg or {}).get("_root") or Path(__file__).resolve().parents[3])
    return root / "data" / "ml" / "exit_lgbm.txt"


def _vectorize(feature_pack: dict[str, Any]) -> list[float]:
    feats = feature_pack.get("features") or {}
    row = []
    for k in FEATURE_KEYS:
        m = feats.get(k) or {}
        if m.get("available") and m.get("value") is not None:
            row.append(float(m["value"]))
        else:
            row.append(0.0)  # impute missing as 0 pressure — documented
    return row


def predict_exit_ml(feature_pack: dict[str, Any], cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    exit_cfg = load_exit_config(cfg)
    ml_cfg = dict(exit_cfg.get("ml") or {})
    if not ml_cfg.get("enabled", True):
        return {"available": False, "note": "ml_disabled"}
    path = _model_path(cfg)
    if not path.exists():
        return {"available": False, "status": "INSUFFICIENT_SAMPLE", "note": "model_not_trained"}
    try:
        import lightgbm as lgb
    except ImportError:
        return {"available": False, "note": "lightgbm_not_installed"}

    booster = lgb.Booster(model_file=str(path))
    x = [_vectorize(feature_pack)]
    pred = float(booster.predict(x)[0])
    # model predicts exit_score in 0..1 or negative forward return — clamp
    score = max(0.0, min(1.0, pred if pred <= 1.5 else 1.0 / (1.0 + abs(pred))))
    return {
        "available": True,
        "exit_score": round(score, 4),
        "action": soft_action(score, exit_cfg.get("thresholds")),
        "confidence": 0.6,
        "mode": "MODEL",
        "model_version": ml_cfg.get("model_name") or "exit_lgbm_v1",
    }


def train_exit_ml(
    samples: list[dict[str, Any]],
    *,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    samples: [{features: feature_pack, label_exit_score or label_forward_return_10d}]
    Label: prefer binary/regression on -forward_return clipped to [0,1] as exit usefulness.
    """
    exit_cfg = load_exit_config(cfg)
    ml_cfg = dict(exit_cfg.get("ml") or {})
    min_n = int(ml_cfg.get("minimum_sample") or exit_cfg.get("minimum_sample") or 80)
    if len(samples) < min_n:
        return {
            "available": False,
            "status": "INSUFFICIENT_SAMPLE",
            "sample_count": len(samples),
            "minimum_sample": min_n,
            "trained": False,
        }
    try:
        import lightgbm as lgb
        import numpy as np
    except ImportError:
        return {"available": False, "note": "lightgbm_not_installed", "trained": False}

    X, y = [], []
    for s in samples:
        fp = s.get("features") or s.get("feature_pack") or {}
        if s.get("label_exit_score") is not None:
            label = float(s["label_exit_score"])
        elif s.get("label_forward_return_10d") is not None:
            # negative forward return → higher exit score label
            fr = float(s["label_forward_return_10d"])
            label = max(0.0, min(1.0, -fr * 5.0 + 0.3))
        else:
            continue
        X.append(_vectorize(fp))
        y.append(label)
    if len(X) < min_n:
        return {
            "available": False,
            "status": "INSUFFICIENT_SAMPLE",
            "sample_count": len(X),
            "minimum_sample": min_n,
            "trained": False,
        }

    # simple holdout walk-forward style split by order
    n = len(X)
    cut = int(n * 0.7)
    Xtr, Xte = np.array(X[:cut]), np.array(X[cut:])
    ytr, yte = np.array(y[:cut]), np.array(y[cut:])
    train_set = lgb.Dataset(Xtr, label=ytr)
    params = {"objective": "regression", "metric": "l2", "verbosity": -1, "num_leaves": 15, "learning_rate": 0.05}
    booster = lgb.train(params, train_set, num_boost_round=80)
    path = _model_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    booster.save_model(str(path))
    pred = booster.predict(Xte) if len(Xte) else []
    mse = float(np.mean((np.array(pred) - yte) ** 2)) if len(pred) else None
    return {
        "available": True,
        "trained": True,
        "sample_count": n,
        "train_n": cut,
        "valid_n": n - cut,
        "mse": mse,
        "model_path": str(path),
        "status": "OK",
        "note": "Walk-forward style 70/30 split; compare vs heuristic in Exit Alpha.",
    }
