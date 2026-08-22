from __future__ import annotations

from typing import Any

from ashare.risk.guard import RiskGuard
from ashare.strategy.ai_select import AISelectStrategy
from ashare.strategy.base import Strategy
from ashare.strategy.dual_ma import DualMAStrategy
from ashare.strategy.leader import LeaderFactorStrategy
from ashare.strategy.ml_lgbm import MLLgbmStrategy
from ashare.strategy.multi_factor import MultiFactorStrategy


def build_strategy(cfg: dict[str, Any]) -> Strategy:
    s = cfg.get("strategy", {})
    r = cfg.get("risk", {})
    ml = cfg.get("ml", {})
    name = str(s.get("name", "leader")).lower()
    common = dict(
        max_name_weight=float(r.get("max_name_weight", 0.20)),
        max_gross_weight=float(r.get("max_gross_weight", 0.95)),
        rebalance_threshold=float(s.get("rebalance_threshold", 0.05)),
    )
    if name in {"leader", "dragon", "leader_factor", "roundtable"}:
        return LeaderFactorStrategy(
            cfg=cfg,
            top_n=int(s.get("top_n", ml.get("top_n", 5))),
            rebalance=str(s.get("rebalance", "week_end")),
            **common,
        )
    if name in {"dual_ma", "ma"}:
        return DualMAStrategy(
            fast=int(s.get("fast", 10)),
            slow=int(s.get("slow", 30)),
            max_positions=int(s.get("max_positions", 8)),
            **common,
        )
    if name in {"multi_factor", "factor"}:
        return MultiFactorStrategy(
            lookback_mom=int(s.get("lookback_mom", 20)),
            lookback_vol=int(s.get("lookback_vol", 20)),
            lookback_value=int(s.get("lookback_value", 60)),
            top_n=int(s.get("top_n", 5)),
            w_mom=float(s.get("w_mom", 0.4)),
            w_vol=float(s.get("w_vol", 0.3)),
            w_value=float(s.get("w_value", 0.3)),
            rebalance=str(s.get("rebalance", "month_end")),
            **common,
        )
    if name in {"ai_select", "ai", "llm"}:
        return AISelectStrategy(
            cfg=cfg,
            top_n=int(s.get("top_n", 5)),
            lookback_mom=int(s.get("lookback_mom", 20)),
            lookback_vol=int(s.get("lookback_vol", 20)),
            lookback_value=int(s.get("lookback_value", 60)),
            **common,
        )
    if name in {"ml_lgbm", "lgbm", "ml"}:
        return MLLgbmStrategy(
            cfg=cfg,
            top_n=int(ml.get("top_n", s.get("top_n", 5))),
            model_path=ml.get("model_path"),
            run_id=ml.get("run_id"),
            **common,
        )
    raise ValueError(f"Unknown strategy: {name}")


def build_risk(cfg: dict[str, Any]) -> RiskGuard:
    r = cfg.get("risk", {})
    return RiskGuard(
        max_name_weight=float(r.get("max_name_weight", 0.20)),
        max_gross_weight=float(r.get("max_gross_weight", 0.95)),
        max_drawdown=float(r.get("max_drawdown", 0.20)),
        max_daily_loss=float(r.get("max_daily_loss", 0.08)),
    )


__all__ = [
    "AISelectStrategy",
    "DualMAStrategy",
    "LeaderFactorStrategy",
    "MLLgbmStrategy",
    "MultiFactorStrategy",
    "Strategy",
    "build_strategy",
    "build_risk",
]
