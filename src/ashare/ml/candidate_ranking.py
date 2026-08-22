from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from ashare.config_loaders import load_yaml_config


def resolve_ml_weight(cfg: dict[str, Any] | None, cw: dict[str, Any] | None = None) -> float:
    """ML weight for candidate_score — research.yaml overrides news.yaml."""
    cw = cw or {}
    ml_cfg = load_yaml_config(cfg or {}, "research").get("ml_ranking") or {}
    if not bool(ml_cfg.get("enabled", True)):
        return 0.0
    return float(ml_cfg.get("weight_in_candidate_score") or cw.get("ml") or 0.10)


def winsorize_rank_percentile(values: dict[str, float], *, lo: float = 0.01, hi: float = 0.99) -> dict[str, float]:
    """
    Cross-sectional winsorize + rank percentile in [0, 1].
    Deterministic; no future data.
    """
    if not values:
        return {}
    if len(values) == 1:
        sym = next(iter(values))
        return {sym: 0.5}
    s = pd.Series(values, dtype=float)
    clip_lo, clip_hi = s.quantile(lo), s.quantile(hi)
    clipped = s.clip(lower=clip_lo, upper=clip_hi)
    ranked = clipped.rank(pct=True, method="average")
    return {str(k): float(v) for k, v in ranked.items()}


def apply_ml_rank_scores(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach ml_rank_score (0–1 percentile) from raw ml_prediction."""
    preds = {
        str(r["symbol"]): float(r["ml_prediction"])
        for r in rows
        if r.get("symbol") and r.get("ml_prediction") is not None
    }
    ranks = winsorize_rank_percentile(preds)
    out: list[dict[str, Any]] = []
    for r in rows:
        item = dict(r)
        sym = str(item.get("symbol") or "")
        if sym in ranks:
            item["ml_rank_score"] = ranks[sym]
        elif item.get("ml_prediction") is not None:
            item["ml_rank_score"] = 0.5
        else:
            item["ml_rank_score"] = None
        out.append(item)
    return out


def compute_candidate_score(item: dict[str, Any], cw: dict[str, Any], ml_weight: float | None = None) -> float:
    """Unified candidate_score using optional ml_rank_score (preferred) or raw ml_prediction."""
    leader = float(item.get("leader_score") or 0)
    pi_score = float((item.get("profit_inflection") or {}).get("score") or 0)
    ev_score = float(item.get("event_score") or 0)
    news = float(item.get("news_score") or 0)
    w_ml = float(ml_weight if ml_weight is not None else cw.get("ml", 0.10))
    if item.get("ml_rank_score") is not None:
        ml_term = float(item["ml_rank_score"])
    elif item.get("ml_prediction") is not None:
        ml_term = float(item["ml_prediction"]) * 10.0
    else:
        ml_term = 0.0
    # Renormalize non-ML weights when ML weight is applied
    base_w = {
        "leader": float(cw.get("leader", 0.35)),
        "profit_inflection": float(cw.get("profit_inflection", 0.25)),
        "event": float(cw.get("event", 0.15)),
        "news": float(cw.get("news", 0.15)),
    }
    base_sum = sum(base_w.values()) or 1.0
    scale = (1.0 - w_ml) / base_sum if w_ml < 1.0 else 0.0
    return (
        scale * base_w["leader"] * leader
        + scale * base_w["profit_inflection"] * pi_score
        + scale * base_w["event"] * ev_score
        + scale * base_w["news"] * news
        + w_ml * ml_term
    )


def rescore_rows(rows: list[dict[str, Any]], cw: dict[str, Any], ml_weight: float | None = None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for r in rows:
        item = dict(r)
        item["candidate_score"] = compute_candidate_score(item, cw, ml_weight=ml_weight)
        out.append(item)
    return out
