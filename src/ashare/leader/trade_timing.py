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
    }
    return {**defaults, **base}


class TradeTimingEngine:
    """
    Separate leader quality from buy timing.
    Outputs: trade_timing_score + action in {BUY_READY, BUY_CANDIDATE, WAIT, PASS}.
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
    ) -> dict[str, Any]:
        st = str(stage or "EARLY").upper()
        base = 0.35 * float(leader_score) + 0.25 * float(factor_score)
        base += 0.10 * min(1.0, float(news_score))
        base += 0.10 * min(1.0, float(event_score))
        base += 0.10 * min(1.0, float(profit_score))
        base -= 0.25 * float(chase_score)
        base -= 0.20 * float(negative_evidence)
        base -= 0.15 * float(risk_score)

        if st == "TREND":
            base += 0.08
        elif st == "ACCELERATION":
            base += 0.04
        elif st == "EARLY":
            base += 0.06
        elif st == "EXTREME":
            base = min(base, float(self.tc["extreme_stage_cap"]))
        elif st == "DISTRIBUTION":
            base -= 0.12
        elif st == "BREAKDOWN":
            base = min(base, float(self.tc["breakdown_cap"]))

        if limit_up:
            base -= 0.08

        score = round(max(0.0, min(1.0, base)), 4)
        action = self._action(score, st)
        return {
            "trade_timing_score": score,
            "trade_timing_action": action,
            "timing_reason": self._reason(action, st, chase_score, limit_up),
        }

    def _action(self, score: float, stage: str) -> str:
        st = str(stage).upper()
        if st == "BREAKDOWN":
            return "PASS"
        if score >= float(self.tc["buy_ready_min"]) and st in {"TREND", "EARLY", "ACCELERATION"}:
            return "BUY_READY"
        if score >= float(self.tc["buy_candidate_min"]):
            return "BUY_CANDIDATE"
        if st == "EXTREME" or score <= float(self.tc["wait_max"]):
            return "WAIT"
        return "WAIT"

    def _reason(self, action: str, stage: str, chase: float, limit_up: bool) -> str:
        bits = [action, f"stage={stage}", f"chase={chase:.2f}"]
        if limit_up:
            bits.append("limit_up_block")
        if stage == "EXTREME":
            bits.append("extreme_wait_not_pass")
        return ";".join(bits)
