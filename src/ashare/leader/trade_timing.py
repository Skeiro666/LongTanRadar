from __future__ import annotations

from typing import Any

from ashare.config_loaders import load_yaml_config


def _timing_cfg(cfg: dict[str, Any] | None) -> dict[str, Any]:
    base = dict(load_yaml_config(cfg, "leader").get("timing") or {})
    defaults = {
        "buy_ready_min": 0.72,
        "buy_candidate_min": 0.55,
        "wait_max": 0.54,
        "extreme_stage_cap": 0.45,
        "breakdown_cap": 0.15,
        "reentry_weight": 0.28,
        "reentry_buy_candidate_min": 0.55,
        "reentry_buy_ready_min": 0.68,
        "extreme_requires_reentry": True,
    }
    return {**defaults, **base}


class TradeTimingEngine:
    """
    Separate leader quality from buy timing.
    Outputs: trade_timing_score + action in {BUY_READY, BUY_CANDIDATE, WAIT, PASS}.
    EXTREME without reentry → WAIT; EXTREME + strong reentry → BUY_CANDIDATE path.
    """

    ACTIONS = ("BUY_READY", "BUY_CANDIDATE", "WAIT", "PASS")

    def __init__(self, cfg: dict[str, Any] | None = None) -> None:
        self.cfg = cfg or {}
        self.tc = _timing_cfg(self.cfg)

    def evaluate(
        self,
        *,
        leader_score: float,
        factor_score: float,
        stage: str,
        chase_score: float,
        news_score: float = 0.0,
        event_score: float = 0.0,
        profit_score: float = 0.0,
        negative_evidence: float = 0.0,
        risk_score: float = 0.0,
        limit_up: bool = False,
        reentry_score: float = 0.0,
        reentry_phase: str = "NONE",
        board_count: int = 0,
    ) -> dict[str, Any]:
        st = str(stage or "EARLY").upper()
        re = float(reentry_score or 0)
        phase = str(reentry_phase or "NONE").upper()
        board = int(board_count or 0)
        base = 0.30 * float(leader_score) + 0.20 * float(factor_score)
        base += 0.08 * min(1.0, float(news_score))
        base += 0.08 * min(1.0, float(event_score))
        base += 0.08 * min(1.0, float(profit_score))
        base += float(self.tc["reentry_weight"]) * re
        base -= 0.22 * float(chase_score)
        base -= 0.18 * float(negative_evidence)
        base -= 0.12 * float(risk_score)

        if st == "TREND":
            base += 0.08
        elif st == "ACCELERATION":
            base += 0.04
        elif st == "EARLY":
            base += 0.06
        elif st == "EXTREME":
            # Cap raw chase-timing, but allow reentry to lift toward BUY_CANDIDATE later.
            if re < float(self.tc["reentry_buy_candidate_min"]) or bool(self.tc.get("extreme_requires_reentry")):
                if phase not in {"REACCELERATION", "BUY_CANDIDATE", "DIVERGENCE", "STABILIZATION", "PULLBACK_WATCH"}:
                    base = min(base, float(self.tc["extreme_stage_cap"]))
                elif limit_up:
                    base = min(base, float(self.tc["extreme_stage_cap"]))
                else:
                    # post-extreme with reentry: lift but never auto BUY_READY on EXTREME label alone
                    base = max(base, 0.35 + 0.45 * re)
                    base = min(base, 0.71)  # below buy_ready_min unless stage leaves EXTREME
        elif st == "DISTRIBUTION":
            base -= 0.12
        elif st == "BREAKDOWN":
            base = min(base, float(self.tc["breakdown_cap"]))

        if limit_up and st == "EXTREME":
            base -= 0.10

        score = round(max(0.0, min(1.0, base)), 4)
        action = self._action(score, st, re=re, phase=phase, limit_up=limit_up, board=board)
        return {
            "trade_timing_score": score,
            "trade_timing_action": action,
            "timing_reason": self._reason(action, st, chase_score, limit_up, re, phase, board),
        }

    def _action(
        self, score: float, stage: str, *, re: float, phase: str, limit_up: bool, board: int
    ) -> str:
        st = str(stage).upper()
        if st == "BREAKDOWN":
            return "PASS"
        # 1板不做龙头买点候选
        if board < 2 and st == "EXTREME":
            return "WAIT"
        # EXTREME same-bar limit-up: always WAIT
        if st == "EXTREME" and limit_up:
            return "WAIT"
        # EXTREME without meaningful reentry → WAIT (not PASS, not BUY)
        if st == "EXTREME" and re < float(self.tc["reentry_buy_candidate_min"]):
            return "WAIT"
        # EXTREME + strong reentry → at most BUY_CANDIDATE (never BUY_READY while still labeled EXTREME)
        if st == "EXTREME" and re >= float(self.tc["reentry_buy_candidate_min"]) and board >= 2:
            if phase in {"REACCELERATION", "BUY_CANDIDATE"} or re >= float(self.tc["reentry_buy_ready_min"]):
                return "BUY_CANDIDATE"
            if phase in {"DIVERGENCE", "PULLBACK_WATCH", "STABILIZATION"}:
                return "WAIT" if score < float(self.tc["buy_candidate_min"]) else "BUY_CANDIDATE"
            return "WAIT"
        if score >= float(self.tc["buy_ready_min"]) and st in {"TREND", "EARLY", "ACCELERATION"} and board >= 2:
            return "BUY_READY"
        if score >= float(self.tc["buy_candidate_min"]) and board >= 2:
            return "BUY_CANDIDATE"
        if st == "EXTREME" or score <= float(self.tc["wait_max"]) or board < 2:
            return "WAIT"
        return "WAIT"

    def _reason(
        self,
        action: str,
        stage: str,
        chase: float,
        limit_up: bool,
        re: float,
        phase: str,
        board: int = 0,
    ) -> str:
        bits = [
            action,
            f"stage={stage}",
            f"board={board}",
            f"chase={chase:.2f}",
            f"reentry={re:.2f}",
            f"phase={phase}",
        ]
        if limit_up:
            bits.append("limit_up_block")
        if board < 2:
            bits.append("board_lt_2_no_buy")
        if stage == "EXTREME" and re < float(self.tc["reentry_buy_candidate_min"]):
            bits.append("extreme_wait_need_reentry")
        if stage == "EXTREME" and action == "BUY_CANDIDATE":
            bits.append("extreme_reentry_improved")
        return ";".join(bits)
