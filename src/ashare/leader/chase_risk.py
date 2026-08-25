from __future__ import annotations

from typing import Any

from ashare.config_loaders import load_yaml_config
from ashare.strategy.anti_chase import chase_penalty


def _chase_cfg(cfg: dict[str, Any] | None) -> dict[str, Any]:
    base = dict(load_yaml_config(cfg, "leader").get("chase") or {})
    defaults = {"low_max": 0.35, "medium_max": 0.55, "high_max": 0.75}
    return {**defaults, **base}


class ChaseRiskEngine:
    """Research chase risk — higher = more dangerous to chase now."""

    LEVELS = ("LOW", "MEDIUM", "HIGH", "EXTREME")

    def __init__(self, cfg: dict[str, Any] | None = None) -> None:
        self.cfg = cfg or {}
        self.cc = _chase_cfg(self.cfg)

    def score(self, feats: dict[str, Any], *, stage: str | None = None) -> float:
        raw = float(chase_penalty(feats, self.cfg))
        ext = 0.0
        ext += max(0.0, float(feats.get("distance_to_MA20") or 0)) * 2.0
        ext += max(0.0, float(feats.get("ret_5") or 0)) * 1.5
        ext += float(feats.get("consecutive_limit_up") or 0) * 0.08
        ext += max(0.0, float(feats.get("turnover_zscore") or 0)) * 0.05
        ext += max(0.0, float(feats.get("volume_acceleration") or 0)) * 0.1
        if str(stage or "").upper() == "EXTREME":
            ext += 0.15
        return round(min(1.0, (raw + ext) / 4.0), 4)

    def level(self, chase_score: float) -> str:
        s = float(chase_score)
        if s <= float(self.cc["low_max"]):
            return "LOW"
        if s <= float(self.cc["medium_max"]):
            return "MEDIUM"
        if s <= float(self.cc["high_max"]):
            return "HIGH"
        return "EXTREME"

    def annotate(self, feats: dict[str, Any], *, stage: str | None = None) -> dict[str, Any]:
        cs = self.score(feats, stage=stage)
        return {
            "chase_score": cs,
            "chase_level": self.level(cs),
            "chase_features": {
                "distance_to_MA5": feats.get("distance_to_MA5"),
                "distance_to_MA20": feats.get("distance_to_MA20"),
                "distance_to_MA60": feats.get("distance_to_MA60"),
                "ret_5": feats.get("ret_5"),
                "consecutive_up_days": feats.get("consecutive_up_days"),
                "limit_up_count_5d": feats.get("limit_up_count_5d"),
                "turnover_zscore": feats.get("turnover_zscore"),
                "volume_acceleration": feats.get("volume_acceleration"),
            },
        }
