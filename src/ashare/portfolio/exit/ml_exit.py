from __future__ import annotations

"""Optional Exit LightGBM — walk-forward only; compare vs Heuristic. No random split."""

from pathlib import Path
from typing import Any

import numpy as np

from ashare.portfolio.exit.config import load_exit_config, soft_action
from ashare.portfolio.exit.heuristic import compute_exit_score


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
    score = max(0.0, min(1.0, pred if pred <= 1.5 else 1.0 / (1.0 + abs(pred))))
    return {
        "available": True,
        "exit_score": round(score, 4),
        "action": soft_action(score, exit_cfg.get("thresholds")),
        "confidence": 0.6,
        "mode": "MODEL",
        "model_version": ml_cfg.get("model_name") or "exit_lgbm_v1",
    }


def _metrics_vs_labels(pred: np.ndarray, y: np.ndarray, fwd: np.ndarray | None) -> dict[str, Any]:
    if len(pred) < 3:
        return {"available": False}
    mae = float(np.mean(np.abs(pred - y)))
    rmse = float(np.sqrt(np.mean((pred - y) ** 2)))
    # Rank IC vs label
    try:
        import pandas as pd

        rank_ic = float(pd.Series(pred).corr(pd.Series(y), method="spearman"))
    except Exception:  # noqa: BLE001
        rank_ic = None
    # Hit rate: same side of median
    med = float(np.median(y))
    hit = float(np.mean(((pred >= med) == (y >= med))))
    dir_acc = None
    if fwd is not None and len(fwd) == len(pred):
        # higher exit score should predict negative fwd return
        dir_acc = float(np.mean(((pred > 0.5) & (fwd < 0)) | ((pred <= 0.5) & (fwd >= 0))))
    return {
        "available": True,
        "mae": mae,
        "rmse": rmse,
        "rank_ic": rank_ic,
        "hit_rate": hit,
        "t10_directional_accuracy": dir_acc,
    }


def compare_ml_vs_heuristic(
    samples: list[dict[str, Any]],
    *,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Walk-forward holdout comparison. Does not train if sample < minimum."""
    exit_cfg = load_exit_config(cfg)
    ml_cfg = dict(exit_cfg.get("ml") or {})
    min_n = int(ml_cfg.get("minimum_sample") or exit_cfg.get("minimum_sample") or 80)
    if len(samples) < min_n:
        return {
            "available": False,
            "status": "INSUFFICIENT_SAMPLE",
            "sample_count": len(samples),
            "minimum_sample": min_n,
            "ml_improves": None,
            "keep": "HEURISTIC",
        }

    X, y, fwd, heur = [], [], [], []
    for s in samples:
        fp = s.get("features") or s.get("feature_pack") or {}
        if s.get("label_exit_score") is not None:
            label = float(s["label_exit_score"])
        elif s.get("label_forward_return_10d") is not None:
            fr = float(s["label_forward_return_10d"])
            label = max(0.0, min(1.0, -fr * 5.0 + 0.3))
            fwd.append(fr)
        else:
            continue
        X.append(_vectorize(fp))
        y.append(label)
        hs = compute_exit_score(fp, cfg)
        heur.append(float(hs.get("exit_score") or 0))
        if "label_forward_return_10d" not in s:
            fwd.append(np.nan)

    n = len(X)
    if n < min_n:
        return {
            "available": False,
            "status": "INSUFFICIENT_SAMPLE",
            "sample_count": n,
            "minimum_sample": min_n,
            "ml_improves": None,
            "keep": "HEURISTIC",
        }

    # Time-ordered split: Train → Validation → Forward test (60/20/20)
    cut_tr = int(n * 0.6)
    cut_va = int(n * 0.8)
    if cut_tr < 20 or (n - cut_va) < 10:
        return {
            "available": False,
            "status": "INSUFFICIENT_SAMPLE",
            "sample_count": n,
            "note": "walk_forward_slices_too_small",
            "ml_improves": None,
            "keep": "HEURISTIC",
        }

    try:
        import lightgbm as lgb
    except ImportError:
        return {"available": False, "note": "lightgbm_not_installed", "keep": "HEURISTIC"}

    Xtr, ytr = np.array(X[:cut_tr]), np.array(y[:cut_tr])
    Xte, yte = np.array(X[cut_va:]), np.array(y[cut_va:])
    hte = np.array(heur[cut_va:])
    fte = np.array(fwd[cut_va:]) if len(fwd) == n else None

    train_set = lgb.Dataset(Xtr, label=ytr)
    params = {"objective": "regression", "metric": "l2", "verbosity": -1, "num_leaves": 15, "learning_rate": 0.05}
    booster = lgb.train(params, train_set, num_boost_round=80)
    pred = np.array(booster.predict(Xte))

    ml_m = _metrics_vs_labels(pred, yte, fte)
    he_m = _metrics_vs_labels(hte, yte, fte)

    # ML improves if lower MAE and better (more negative / higher abs) rank IC vs heuristic
    improves = False
    if ml_m.get("available") and he_m.get("available"):
        mae_better = ml_m["mae"] < he_m["mae"] * 0.95
        ic_ml = ml_m.get("rank_ic")
        ic_he = he_m.get("rank_ic")
        ic_better = ic_ml is not None and ic_he is not None and abs(ic_ml) > abs(ic_he) + 0.02
        dir_better = (
            ml_m.get("t10_directional_accuracy") is not None
            and he_m.get("t10_directional_accuracy") is not None
            and ml_m["t10_directional_accuracy"] > he_m["t10_directional_accuracy"] + 0.02
        )
        improves = bool(mae_better and (ic_better or dir_better))

    return {
        "available": True,
        "status": "OK",
        "sample_count": n,
        "train_n": cut_tr,
        "valid_n": cut_va - cut_tr,
        "test_n": n - cut_va,
        "split": "time_ordered_60_20_20",
        "ml": ml_m,
        "heuristic": he_m,
        "ml_improves": improves,
        "keep": "MODEL" if improves else "HEURISTIC",
        "note": "No random shuffle. Future rows never enter past training.",
    }


def train_exit_ml(
    samples: list[dict[str, Any]],
    *,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Train only when walk-forward sample enough AND comparison says ML improves.
    Otherwise keep HEURISTIC and do not overwrite a weak model claim.
    """
    cmp = compare_ml_vs_heuristic(samples, cfg=cfg)
    if not cmp.get("available"):
        return {**cmp, "trained": False}

    if not cmp.get("ml_improves"):
        return {
            **cmp,
            "trained": False,
            "status": "OK",
            "note": "ML did not clearly beat Heuristic — keeping HEURISTIC. Model not activated.",
        }

    exit_cfg = load_exit_config(cfg)
    ml_cfg = dict(exit_cfg.get("ml") or {})
    min_n = int(ml_cfg.get("minimum_sample") or 80)

    X, y = [], []
    for s in samples:
        fp = s.get("features") or s.get("feature_pack") or {}
        if s.get("label_exit_score") is not None:
            label = float(s["label_exit_score"])
        elif s.get("label_forward_return_10d") is not None:
            fr = float(s["label_forward_return_10d"])
            label = max(0.0, min(1.0, -fr * 5.0 + 0.3))
        else:
            continue
        X.append(_vectorize(fp))
        y.append(label)
    if len(X) < min_n:
        return {**cmp, "trained": False, "status": "INSUFFICIENT_SAMPLE"}

    try:
        import lightgbm as lgb
    except ImportError:
        return {**cmp, "trained": False, "note": "lightgbm_not_installed"}

    # Retrain on train+valid (first 80%), leave last 20% unused for honesty
    cut = int(len(X) * 0.8)
    train_set = lgb.Dataset(np.array(X[:cut]), label=np.array(y[:cut]))
    params = {"objective": "regression", "metric": "l2", "verbosity": -1, "num_leaves": 15, "learning_rate": 0.05}
    booster = lgb.train(params, train_set, num_boost_round=80)
    path = _model_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    booster.save_model(str(path))
    return {
        **cmp,
        "trained": True,
        "model_path": str(path),
        "status": "OK",
        "vs_heuristic": cmp,
    }
