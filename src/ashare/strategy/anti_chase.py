from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

FEATURE_NOTE = (
    "均线偏离是均值回归技术因子，不是基本面 Value。"
    "大阴线当日不买；破位（跌破MA60且近20日新低）时 MR 权重清零；"
    "ML 预测收益低于成本缓冲不交易。"
)


def anti_chase_cfg(cfg: dict[str, Any]) -> dict[str, Any]:
    defaults = {
        "max_daily_ret": 0.02,
        "max_mom20": 0.12,
        "max_ma_gap20": 0.06,
        "penalty_daily": 3.0,
        "penalty_mom5": 1.5,
        "penalty_mom20": 2.0,
        "penalty_ma_gap": 2.0,
        # 大阴线当日禁止开仓（避免接飞刀）
        "ban_dump_ret": -0.04,
    }
    raw = dict((cfg.get("strategy") or {}).get("anti_chase") or {})
    return {**defaults, **raw}


def scoring_cfg(cfg: dict[str, Any]) -> dict[str, Any]:
    st = cfg.get("strategy") or {}
    defaults = {
        "w_ml_z": 0.55,
        "w_mr_z": 0.45,
        "require_ml_nonneg": True,
        "conflict_penalty": 1.2,
        "agree_weight": 1.0,
        "mr_only_weight_scale": 0.25,
        "ml_only_weight_scale": 0.5,
        # ML 原始预测过低（相对成本）不买
        "min_ml_pred": 0.006,
        # 破位：MA60下方 + 近20日新低 → MR 贡献清零
        "zero_mr_on_breakdown": True,
        # 破位且仅靠回调叙事时直接跳过
        "skip_breakdown_without_ml": True,
    }
    raw = dict(st.get("scoring") or {})
    return {**defaults, **raw}


def enrich_structure(feats: dict[str, float], closes: pd.Series) -> dict[str, float]:
    """Add breakdown / 20d-low structure flags from close series."""
    out = dict(feats)
    c = closes.astype(float)
    if len(c) < 20:
        out["near_20d_low"] = 0.0
        out["is_breakdown"] = 0.0
        return out
    last = float(c.iloc[-1])
    low20 = float(c.tail(20).min())
    near = 1.0 if last <= low20 * 1.01 else 0.0
    below60 = 1.0 if float(out.get("ma_gap_60", 0.0)) < 0 else 0.0
    out["near_20d_low"] = near
    out["is_breakdown"] = 1.0 if (near > 0 and below60 > 0) else 0.0
    return out


def passes_anti_chase(feats: dict[str, float], cfg: dict[str, Any]) -> bool:
    """Skip chase-up names and same-day dump knives."""
    ac = anti_chase_cfg(cfg)
    if feats.get("ret_1", 0.0) > float(ac["max_daily_ret"]):
        return False
    if feats.get("mom_20", 0.0) > float(ac["max_mom20"]):
        return False
    if feats.get("ma_gap_20", 0.0) > float(ac["max_ma_gap20"]):
        return False
    # 大阴线当日不买
    if feats.get("ret_1", 0.0) < float(ac["ban_dump_ret"]):
        return False
    return True


def passes_ml_floor(ml_score: float, cfg: dict[str, Any]) -> bool:
    sc = scoring_cfg(cfg)
    return float(ml_score) >= float(sc["min_ml_pred"])


def chase_penalty(feats: dict[str, float], cfg: dict[str, Any]) -> float:
    ac = anti_chase_cfg(cfg)
    return (
        max(0.0, feats.get("ret_1", 0.0)) * float(ac["penalty_daily"])
        + max(0.0, feats.get("mom_5", 0.0)) * float(ac["penalty_mom5"])
        + max(0.0, feats.get("mom_20", 0.0)) * float(ac["penalty_mom20"])
        + max(0.0, feats.get("ma_gap_20", 0.0)) * float(ac["penalty_ma_gap"])
    )


def mean_reversion_score(feats: dict[str, float], *, allow_breakdown: bool = False) -> float:
    """Technical pullback vs MA — NOT fundamental value. Zeroed on breakdown."""
    if not allow_breakdown and float(feats.get("is_breakdown", 0.0)) > 0:
        return 0.0
    return -float(feats.get("ma_gap_20", 0.0)) * 0.6 - float(feats.get("ma_gap_60", 0.0)) * 0.4


def value_score(feats: dict[str, float]) -> float:
    return mean_reversion_score(feats)


def _zscore_map(values: dict[str, float]) -> dict[str, float]:
    if not values:
        return {}
    arr = np.array(list(values.values()), dtype=float)
    std = float(arr.std())
    mean = float(arr.mean())
    if std < 1e-12:
        return {k: 0.0 for k in values}
    return {k: float((v - mean) / std) for k, v in values.items()}


def rank_score(ml_score: float, feats: dict[str, float], cfg: dict[str, Any]) -> float:
    style = str((cfg.get("strategy") or {}).get("picks_style", "agree")).lower()
    penalty = chase_penalty(feats, cfg)
    mr = mean_reversion_score(feats)
    if style == "momentum":
        return ml_score
    if style in {"value", "mean_reversion", "mr"}:
        return mr * 0.3 + ml_score * 0.7 - penalty
    return ml_score * 0.7 + mr * 0.3 - penalty


def score_cross_section(
    candidates: list[dict[str, Any]],
    cfg: dict[str, Any],
) -> list[dict[str, Any]]:
    if not candidates:
        return []

    style = str((cfg.get("strategy") or {}).get("picks_style", "agree")).lower()
    sc = scoring_cfg(cfg)
    w_ml = float(sc["w_ml_z"])
    w_mr = float(sc["w_mr_z"])
    s = w_ml + w_mr
    if s > 0:
        w_ml, w_mr = w_ml / s, w_mr / s

    zero_mr = bool(sc["zero_mr_on_breakdown"])
    ml_map = {c["symbol"]: float(c["ml_score"]) for c in candidates}
    mr_map = {
        c["symbol"]: mean_reversion_score(c["feats"], allow_breakdown=not zero_mr) for c in candidates
    }
    ml_z = _zscore_map(ml_map)
    mr_z = _zscore_map(mr_map)

    out: list[dict[str, Any]] = []
    for c in candidates:
        sym = c["symbol"]
        feats = c["feats"]
        ml = float(c["ml_score"])
        mr = mr_map[sym]
        mz = ml_z[sym]
        rz = mr_z[sym]
        pen = chase_penalty(feats, cfg)
        breakdown = float(feats.get("is_breakdown", 0.0)) > 0
        dump = float(feats.get("ret_1", 0.0)) < float(anti_chase_cfg(cfg)["ban_dump_ret"])

        conflict = mz < 0 and rz > 0.5
        agree = mz > 0 and rz > 0
        ml_ok = mz >= 0
        ml_floor_ok = ml >= float(sc["min_ml_pred"])

        if style == "momentum":
            score = mz
            weight_scale = 1.0 if ml_ok and ml_floor_ok else 0.0
            agreement = "ml_only" if weight_scale > 0 else "ml_floor_skip"
        elif style in {"value", "mean_reversion", "mr"}:
            score = w_mr * rz + w_ml * mz - (float(sc["conflict_penalty"]) * abs(mz) if conflict else 0.0)
            if not ml_floor_ok:
                weight_scale = 0.0
                agreement = "ml_floor_skip"
            elif bool(sc["require_ml_nonneg"]) and not ml_ok:
                weight_scale = 0.0
                agreement = "conflict_skip"
            elif breakdown and bool(sc["skip_breakdown_without_ml"]) and rz <= 0:
                weight_scale = float(sc["ml_only_weight_scale"]) if ml_ok else 0.0
                agreement = "breakdown_ml_only" if weight_scale > 0 else "breakdown_skip"
            elif agree:
                weight_scale = float(sc["agree_weight"])
                agreement = "agree"
            elif conflict:
                weight_scale = float(sc["mr_only_weight_scale"])
                agreement = "conflict_mr"
            elif ml_ok:
                weight_scale = float(sc["ml_only_weight_scale"])
                agreement = "ml_lead"
            else:
                weight_scale = 0.0
                agreement = "reject"
            score -= pen * 0.1
        else:
            score = w_ml * mz + w_mr * rz
            if conflict:
                score -= float(sc["conflict_penalty"]) * abs(mz)
            if not ml_floor_ok:
                weight_scale = 0.0
                agreement = "ml_floor_skip"
            elif bool(sc["require_ml_nonneg"]) and not ml_ok:
                weight_scale = 0.0
                agreement = "conflict_skip"
            elif breakdown:
                # 破位：不许用「便宜」加分；仅当 ML 仍够强才小仓
                score = w_ml * mz  # drop MR
                if ml_ok and ml_floor_ok:
                    weight_scale = float(sc["ml_only_weight_scale"]) * 0.5
                    agreement = "breakdown_cautious"
                else:
                    weight_scale = 0.0
                    agreement = "breakdown_skip"
            elif agree:
                weight_scale = float(sc["agree_weight"])
                agreement = "agree"
            elif ml_ok and rz <= 0:
                weight_scale = float(sc["ml_only_weight_scale"])
                agreement = "ml_lead"
            else:
                weight_scale = 0.0
                agreement = "reject"
            score -= pen * 0.1

        # dump day should already be filtered, but belt-and-suspenders
        if dump:
            weight_scale = 0.0
            agreement = "dump_day_skip"

        why_bits: list[str] = []
        why_bits.append(f"ML_z={mz:+.2f}(raw={ml:+.4f})")
        why_bits.append(f"均值回归_z={rz:+.2f}(raw={mr:+.4f})")
        if agreement == "agree":
            why_bits.append("ML与回调同向")
        elif agreement == "conflict_skip":
            why_bits.append("ML看空→跳过")
        elif agreement == "ml_floor_skip":
            why_bits.append(f"ML预测{ml:.4f}<门槛{float(sc['min_ml_pred']):.4f}→跳过")
        elif agreement == "dump_day_skip":
            why_bits.append(f"当日大跌{feats.get('ret_1',0)*100:.1f}%→禁止开仓")
        elif agreement == "breakdown_skip":
            why_bits.append("破位(MA60下+近20日低)→跳过")
        elif agreement == "breakdown_cautious":
            why_bits.append("破位结构→仅弱化ML仓")
        elif agreement == "ml_lead":
            why_bits.append("以模型为主")
        if breakdown:
            why_bits.append("结构=破位")
        if feats.get("mom_5", 0) < -0.03:
            why_bits.append(f"近5日{feats['mom_5']*100:.1f}%")

        out.append(
            {
                **{k: v for k, v in c.items() if k != "feats"},
                "feats": feats,
                "ml_score": ml,
                "value_score": mr,
                "mean_reversion": mr,
                "ml_z": round(mz, 4),
                "mr_z": round(rz, 4),
                "score": float(score),
                "agreement": agreement,
                "weight_scale": float(weight_scale),
                "is_breakdown": breakdown,
                "chase_penalty": pen,
                "why": "；".join(why_bits),
                "factor_note": FEATURE_NOTE,
            }
        )

    out.sort(key=lambda r: (r["weight_scale"] > 0, r["score"]), reverse=True)
    return out


def allocate_weights(
    ranked: list[dict[str, Any]],
    *,
    top_n: int,
    max_name_weight: float,
) -> list[dict[str, Any]]:
    eligible = [r for r in ranked if float(r.get("weight_scale") or 0) > 0][:top_n]
    if not eligible:
        return []
    scales = [float(r["weight_scale"]) for r in eligible]
    s = sum(scales) or 1.0
    out = []
    for r, scv in zip(eligible, scales):
        item = dict(r)
        item["weight"] = min(max_name_weight, scv / s)
        out.append(item)
    tot = sum(float(x["weight"]) for x in out) or 1.0
    if tot > 1.0 + 1e-9:
        for x in out:
            x["weight"] = float(x["weight"]) / tot
    return out
