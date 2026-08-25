from __future__ import annotations

from typing import Any

from ashare.config_loaders import load_yaml_config


def _stage_cfg(cfg: dict[str, Any] | None) -> dict[str, Any]:
    base = dict(load_yaml_config(cfg, "leader").get("stage") or {})
    defaults = {
        "extreme_board_min": 3,
        "extreme_ma_gap20": 0.08,
        "extreme_mom5": 0.25,
    }
    return {**defaults, **base}


class StageEngine:
    """Classify price structure stage using T-day data only."""

    STAGES = ("EARLY", "TREND", "ACCELERATION", "EXTREME", "DISTRIBUTION", "BREAKDOWN")

    def __init__(self, cfg: dict[str, Any] | None = None) -> None:
        self.cfg = cfg or {}
        self.sc = _stage_cfg(self.cfg)

    def classify(self, feats: dict[str, Any], pool_row: dict[str, Any] | None = None) -> str:
        board = int((pool_row or {}).get("board_count") or feats.get("consecutive_limit_up") or 0)
        mom5 = float(feats.get("mom_5") or feats.get("ret_5") or 0)
        mom20 = float(feats.get("mom_20") or feats.get("ret_20") or 0)
        gap20 = float(feats.get("ma_gap_20") or feats.get("distance_to_MA20") or 0)
        gap60 = float(feats.get("ma_gap_60") or feats.get("distance_to_MA60") or 0)
        lu20 = float(feats.get("limit_up_count_20d") or 0)
        breakdown = float(feats.get("is_breakdown") or 0) > 0 or float(feats.get("drawdown_20d") or 0) < -0.12
        ret1 = float(feats.get("ret_1") or 0)
        if breakdown or (gap60 < -0.05 and mom5 < -0.03):
            return "BREAKDOWN"
        if (
            board >= int(self.sc["extreme_board_min"])
            or gap20 > float(self.sc["extreme_ma_gap20"])
            or lu20 >= 3
            or mom5 > float(self.sc["extreme_mom5"])
        ):
            return "EXTREME"
        if ret1 < -0.05 and mom5 > 0.1:
            return "DISTRIBUTION"
        if mom5 > 0.12 and mom20 > 0.08:
            return "ACCELERATION"
        if mom20 > 0.05 and gap20 > 0.02:
            return "TREND"
        return "EARLY"

    def annotate(self, row: dict[str, Any], feats: dict[str, Any]) -> dict[str, Any]:
        stage = self.classify(feats, row)
        return {
            "stage": stage,
            "stage_features": {
                "mom_5": feats.get("mom_5"),
                "mom_20": feats.get("mom_20"),
                "ma_gap_20": feats.get("ma_gap_20"),
                "ma_gap_60": feats.get("ma_gap_60"),
                "consecutive_limit_up": feats.get("consecutive_limit_up"),
                "limit_up_count_5d": feats.get("limit_up_count_5d"),
                "turnover_zscore": feats.get("turnover_zscore"),
            },
        }
