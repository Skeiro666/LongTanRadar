from __future__ import annotations

from typing import Any

from ashare.config_loaders import load_yaml_config


def _rank_cfg(cfg: dict[str, Any] | None) -> dict[str, Any]:
    base = dict(load_yaml_config(cfg, "leader").get("ranking") or {})
    defaults = {
        "weight_board": 0.35,
        "weight_consecutive": 0.25,
        "weight_leader_score": 0.25,
        "weight_event": 0.15,
    }
    return {**defaults, **base}


class LeaderRankingEngine:
    """Leader identification score — separate from trade timing."""

    def __init__(self, cfg: dict[str, Any] | None = None) -> None:
        self.cfg = cfg or {}
        self.rc = _rank_cfg(self.cfg)

    def score(
        self,
        row: dict[str, Any],
        feats: dict[str, Any],
        *,
        factor_leader: float = 0.0,
    ) -> float:
        board = int(row.get("board_count") or 0)
        cons = float(feats.get("consecutive_limit_up") or 0)
        ev = float(row.get("event_score") or 0)
        fl = float(factor_leader or row.get("leader_score") or 0)
        w_b = float(self.rc["weight_board"])
        w_c = float(self.rc["weight_consecutive"])
        w_l = float(self.rc["weight_leader_score"])
        w_e = float(self.rc["weight_event"])
        board_norm = min(1.0, board / 5.0)
        cons_norm = min(1.0, cons / 5.0)
        ev_norm = min(1.0, ev / 2.0)
        raw = w_b * board_norm + w_c * cons_norm + w_l * min(1.0, fl) + w_e * ev_norm
        return round(min(1.5, raw * 1.2), 4)

    def annotate(self, row: dict[str, Any], feats: dict[str, Any]) -> dict[str, Any]:
        ls = self.score(row, feats, factor_leader=float(row.get("leader_score") or 0))
        return {
            "leader_score": ls,
            "leader_rank_features": {
                "board_count": row.get("board_count"),
                "consecutive_limit_up": feats.get("consecutive_limit_up"),
                "limit_up_count_5d": feats.get("limit_up_count_5d"),
                "event_score": row.get("event_score"),
            },
        }
