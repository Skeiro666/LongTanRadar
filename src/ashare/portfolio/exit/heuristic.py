from __future__ import annotations

"""Heuristic Exit Score — MODE=HEURISTIC. Never pretends to be ML."""

from typing import Any

from ashare.portfolio.exit.config import load_exit_config, soft_action


def compute_exit_score(
    feature_pack: dict[str, Any],
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    exit_cfg = load_exit_config(cfg)
    weights = dict(exit_cfg.get("weights") or {})
    feats = dict(feature_pack.get("features") or {})
    numbered: list[tuple[str, float, float]] = []
    for name, meta in feats.items():
        if not meta.get("available") or meta.get("value") is None:
            continue
        w = float(weights.get(name, 0.0))
        if w <= 0:
            continue
        numbered.append((name, float(meta["value"]), w))

    if not numbered:
        return {
            "exit_score": 0.0,
            "action": "HOLD",
            "confidence": 0.0,
            "mode": "HEURISTIC",
            "reasons": [],
            "reason_details": [],
            "available": False,
            "note": "no_available_features",
        }

    wsum = sum(w for _, _, w in numbered) or 1.0
    score = sum(v * w for _, v, w in numbered) / wsum
    score = max(0.0, min(1.0, score))

    ranked = sorted(numbered, key=lambda x: x[1] * x[2], reverse=True)
    reasons = [n for n, v, _ in ranked if v >= 0.25][:5]
    reason_details = [
        {"name": n, "value": round(v, 4), "weight": w, "contribution": round(v * w / wsum, 4)}
        for n, v, w in ranked[:5]
    ]

    min_feat = int((exit_cfg.get("confidence") or {}).get("min_features", 4))
    base_conf = float((exit_cfg.get("confidence") or {}).get("default", 0.55))
    conf = base_conf * min(1.0, len(numbered) / max(min_feat, 1))

    action = soft_action(score, exit_cfg.get("thresholds"))
    # Soft band 0.30–0.60: HOLD unless top reason very strong
    hold_max = float((exit_cfg.get("thresholds") or {}).get("hold_max", 0.30))
    hold_reduce_max = float((exit_cfg.get("thresholds") or {}).get("hold_reduce_max", 0.60))
    if hold_max < score <= hold_reduce_max and ranked and ranked[0][1] >= 0.7:
        action = "REDUCE"

    return {
        "exit_score": round(score, 4),
        "action": action,
        "confidence": round(conf, 4),
        "mode": "HEURISTIC",
        "reasons": reasons,
        "reason_details": reason_details,
        "available": True,
        "n_features_used": len(numbered),
        "exit_types": _classify_exit_types(reasons),
    }


def _classify_exit_types(reasons: list[str]) -> list[str]:
    types: list[str] = []
    risk = {"drawdown", "volatility", "price_extension", "breakout_failure", "moving_average_break"}
    alpha = {"trend_decay", "momentum_decay", "relative_strength_decay", "volume_distribution", "ml_forward_return"}
    event = {"news_reversal", "event_completion"}
    portfolio = {"portfolio_concentration", "time_in_position", "profit_loss"}
    if set(reasons) & risk:
        types.append("RISK_EXIT")
    if set(reasons) & alpha:
        types.append("ALPHA_EXIT")
    if set(reasons) & event:
        types.append("EVENT_EXIT")
    if set(reasons) & portfolio:
        types.append("PORTFOLIO_EXIT")
    return types or ["ALPHA_EXIT"]


REASON_ZH = {
    "trend_decay": "趋势衰减（均线斜率转弱）",
    "momentum_decay": "动量衰减（短周期弱于前期）",
    "relative_strength_decay": "相对强弱转弱",
    "volume_distribution": "量价分布不利（下跌放量/冲高缩量）",
    "price_extension": "价格过度延伸（风险）",
    "drawdown": "自高点回撤扩大",
    "volatility": "波动率抬升",
    "breakout_failure": "突破失败回落",
    "moving_average_break": "跌破关键均线",
    "news_reversal": "新闻方向反转",
    "event_completion": "事件兑现/失效",
    "time_in_position": "持仓时间偏长（软衰减）",
    "profit_loss": "浮盈回吐或浮亏加深",
    "portfolio_concentration": "组合集中度过高",
    "ml_forward_return": "模型预期收益转负",
}


def top_reason_texts(reasons: list[str], limit: int = 3) -> list[str]:
    return [REASON_ZH.get(r, r) for r in reasons[:limit]]
