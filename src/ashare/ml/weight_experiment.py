from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import numpy as np
import pandas as pd

from ashare.config_loaders import load_yaml_config
from ashare.ml.candidate_ranking import apply_ml_rank_scores, compute_candidate_score
from ashare.ml.ranking import MLRankingEngine, _spearman_ic
from ashare.ml.walk_forward import walk_forward_folds

logger = logging.getLogger("ashare.ml.weight_experiment")

DEFAULT_ML_WEIGHTS = (0.0, 0.05, 0.10, 0.15, 0.20)
DEFAULT_HORIZONS = (1, 5, 10, 20)


def _max_drawdown(returns: np.ndarray) -> float:
    if len(returns) == 0:
        return 0.0
    cum = np.cumsum(returns)
    peak = np.maximum.accumulate(cum)
    dd = peak - cum
    return float(np.max(dd)) if len(dd) else 0.0


def _fold_topk_metrics(
    test: pd.DataFrame,
    preds: np.ndarray,
    *,
    ml_weight: float,
    top_k: int = 20,
    horizons: tuple[int, ...] = DEFAULT_HORIZONS,
) -> dict[str, Any]:
    """Per-fold metrics for one ML weight on walk-forward test slice."""
    d = test.copy()
    d["ml_pred"] = preds
    cw = {"leader": 0.35, "profit_inflection": 0.25, "event": 0.15, "news": 0.15, "ml": ml_weight}
    horizon_cols = {h: f"fwd_excess_{h}d" for h in horizons}

    bucket: dict[int, list[float]] = {h: [] for h in horizons}
    hits: dict[int, list[bool]] = {h: [] for h in horizons}
    all_rets: list[float] = []

    for dt, grp in d.groupby("date"):
        if len(grp) < 3:
            continue
        ranks = apply_ml_rank_scores(
            [{"symbol": row["symbol"], "ml_prediction": float(row["ml_pred"]), **row.to_dict()} for _, row in grp.iterrows()]
        )
        for r in ranks:
            r["leader_score"] = float(r.get("leader_score") or r.get("factor_score") or 0)
            r["event_score"] = float(r.get("event_score") or 0)
            r["news_score"] = float(r.get("news_score") or 0)
            r["profit_inflection"] = r.get("profit_inflection") or {"score": 0.0}
            r["candidate_score"] = compute_candidate_score(r, cw, ml_weight=ml_weight)
        ranks.sort(key=lambda x: x["candidate_score"], reverse=True)
        top = ranks[:top_k]
        sym_set = {r["symbol"] for r in top}
        sub = grp[grp["symbol"].isin(sym_set)]
        for h in horizons:
            col = horizon_cols[h]
            if col not in sub.columns:
                alt = f"target_{h}d" if f"target_{h}d" in sub.columns else "target"
                col = alt if alt in sub.columns else None
            if col is None:
                continue
            vals = sub[col].astype(float).dropna()
            if vals.empty:
                continue
            mean_r = float(vals.mean())
            bucket[h].append(mean_r)
            hits[h].append(mean_r > 0)
            if h == horizons[len(horizons) // 2]:
                all_rets.append(mean_r)

    out: dict[str, Any] = {"sample_count": sum(len(v) for v in bucket.values()), "horizons": {}}
    for h in horizons:
        arr = np.array(bucket[h], dtype=float)
        out["horizons"][str(h)] = {
            "excess_return": float(arr.mean()) if len(arr) else None,
            "hit_rate": float(np.mean(hits[h])) if hits[h] else None,
            "sample_count": int(len(arr)),
        }
    out["max_drawdown"] = _max_drawdown(np.array(all_rets, dtype=float))
    return out


def run_ml_weight_experiment(
    panel: dict[str, pd.DataFrame],
    cfg: dict[str, Any] | None = None,
    *,
    weights: tuple[float, ...] = DEFAULT_ML_WEIGHTS,
    horizons: tuple[int, ...] = DEFAULT_HORIZONS,
    persist: bool = True,
) -> dict[str, Any]:
    """
    Walk-forward ML weight grid search. Does NOT modify production config.
    """
    cfg = cfg or {}
    engine = MLRankingEngine(cfg)
    data = engine.build_training_frame(panel)
    if len(data) < 100:
        return {
            "available": False,
            "insufficient_sample": True,
            "sample_count": len(data),
            "note": "need >= 100 training rows",
        }

    wf = dict((load_yaml_config(cfg, "models").get("lgbm") or {}).get("walk_forward") or {})
    folds = walk_forward_folds(
        data,
        train_years=int(wf.get("train_years", 3)),
        test_years=int(wf.get("test_years", 1)),
        embargos_days=int(wf.get("embargos_days", 5)),
    )
    if not folds:
        return {"available": False, "insufficient_sample": True, "note": "no walk-forward folds"}

    weight_results: dict[str, Any] = {}
    for w in weights:
        fold_metrics: list[dict[str, Any]] = []
        for fold in folds:
            x_tr = np.nan_to_num(fold.train[engine.feature_cols].astype(float).values)
            y_tr = fold.train["target"].astype(float).values
            x_te = np.nan_to_num(fold.test[engine.feature_cols].astype(float).values)
            y_te = fold.test["target"].astype(float).values
            model = engine._fit_one(x_tr, y_tr, x_te, y_te)
            preds = model.predict(x_te)
            ic = _spearman_ic(y_te, preds)
            test = fold.test.copy()
            test["leader_score"] = test.get("leader_score", test.get("factor_score", 0))
            m = _fold_topk_metrics(test, preds, ml_weight=w, horizons=horizons)
            m["fold"] = fold.name
            m["oos_ic"] = ic
            fold_metrics.append(m)
        agg: dict[str, Any] = {"ml_weight": w, "folds": fold_metrics, "fold_count": len(fold_metrics)}
        for h in horizons:
            hs = str(h)
            rets = [f["horizons"].get(hs, {}).get("excess_return") for f in fold_metrics if f["horizons"].get(hs, {}).get("excess_return") is not None]
            hits = [f["horizons"].get(hs, {}).get("hit_rate") for f in fold_metrics if f["horizons"].get(hs, {}).get("hit_rate") is not None]
            agg.setdefault("horizons", {})[hs] = {
                "excess_return": float(np.mean(rets)) if rets else None,
                "hit_rate": float(np.mean(hits)) if hits else None,
                "sample_count": len(rets),
            }
        dds = [f.get("max_drawdown") for f in fold_metrics if f.get("max_drawdown") is not None]
        agg["max_drawdown"] = float(np.mean(dds)) if dds else None
        weight_results[str(w)] = agg

    experiment = {
        "experiment_id": f"mlw_{datetime.now(timezone.utc).strftime('%Y%m%d')}_{uuid4().hex[:8]}",
        "available": True,
        "insufficient_sample": False,
        "status": "completed",
        "method": "walk_forward",
        "weights_tested": list(weights),
        "horizons": list(horizons),
        "results": weight_results,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "note": "Descriptive experiment — do not auto-apply best weight to production",
    }
    if persist:
        root = Path(cfg.get("_root") or Path(__file__).resolve().parents[2])
        out_dir = root / "data" / "ml"
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / "weight_experiments.jsonl"
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(experiment, ensure_ascii=False, default=str) + "\n")
    return experiment


def list_weight_experiments(cfg: dict[str, Any], *, limit: int = 20) -> list[dict[str, Any]]:
    root = Path(cfg.get("_root") or Path(__file__).resolve().parents[2])
    path = root / "data" / "ml" / "weight_experiments.jsonl"
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows[-limit:]
