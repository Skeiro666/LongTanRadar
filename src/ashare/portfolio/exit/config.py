from __future__ import annotations

from typing import Any

from ashare.config_loaders import load_yaml_config


def load_exit_config(cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    return load_yaml_config(cfg, "exit")


def score_to_action(exit_score: float, thresholds: dict[str, Any] | None = None) -> str:
    thr = thresholds or {}
    hold_max = float(thr.get("hold_max", 0.30))
    hold_reduce_max = float(thr.get("hold_reduce_max", 0.60))
    reduce_max = float(thr.get("reduce_max", 0.80))
    s = max(0.0, min(1.0, float(exit_score)))
    if s <= hold_max:
        return "HOLD"
    if s <= hold_reduce_max:
        return "HOLD"  # soft zone — still HOLD unless caller upgrades
    if s <= reduce_max:
        return "REDUCE"
    return "EXIT"


def soft_action(exit_score: float, thresholds: dict[str, Any] | None = None) -> str:
    """Map score including soft HOLD/REDUCE band (0.30–0.60 → HOLD with note)."""
    thr = thresholds or {}
    hold_max = float(thr.get("hold_max", 0.30))
    hold_reduce_max = float(thr.get("hold_reduce_max", 0.60))
    reduce_max = float(thr.get("reduce_max", 0.80))
    s = max(0.0, min(1.0, float(exit_score)))
    if s <= hold_max:
        return "HOLD"
    if s <= hold_reduce_max:
        return "HOLD"
    if s <= reduce_max:
        return "REDUCE"
    return "EXIT"
