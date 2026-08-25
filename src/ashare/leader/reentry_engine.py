from __future__ import annotations

from typing import Any

from ashare.config_loaders import load_yaml_config
from ashare.leader.pullback_features import compute_pullback_features


def _reentry_cfg(cfg: dict[str, Any] | None) -> dict[str, Any]:
    base = dict(load_yaml_config(cfg, "leader").get("reentry") or {})
    defaults = {
        "w_structure": 0.25,
        "w_pullback": 0.20,
        "w_volume": 0.20,
        "w_reacceleration": 0.20,
        "w_confirmation": 0.15,
        "buy_candidate_min": 0.55,
        "strong_min": 0.68,
        "healthy_divergence_bonus": 0.12,
        "structure_break_penalty": 0.45,
        "negative_news_penalty": 0.35,
    }
    return {**defaults, **base}


class ReentryEngine:
    """
    After EXTREME → WAIT, score whether pullback / divergence / re-acceleration
    makes the risk-reward acceptable again.
    """

    PHASES = (
        "NONE",
        "WAIT",
        "PULLBACK_WATCH",
        "DIVERGENCE",
        "STABILIZATION",
        "REACCELERATION",
        "BUY_CANDIDATE",
    )

    def __init__(self, cfg: dict[str, Any] | None = None) -> None:
        self.cfg = cfg or {}
        self.rc = _reentry_cfg(self.cfg)

    def evaluate(
        self,
        feats: dict[str, Any],
        *,
        stage: str,
        chase_score: float,
        news_score: float = 0.0,
        negative_evidence: float = 0.0,
        limit_up: bool = False,
        as_of: str | None = None,
        bars=None,
    ) -> dict[str, Any]:
        pb = dict(feats)
        if bars is not None:
            pb.update(compute_pullback_features(bars, as_of=as_of, base_feats=feats))

        structure = self._structure_score(pb)
        pullback = self._pullback_score(pb, stage=stage)
        volume = self._volume_score(pb)
        reaccel = self._reaccel_score(pb)
        confirm = self._confirmation_score(pb, news_score=news_score, negative_evidence=negative_evidence)

        w_s = float(self.rc["w_structure"])
        w_p = float(self.rc["w_pullback"])
        w_v = float(self.rc["w_volume"])
        w_r = float(self.rc["w_reacceleration"])
        w_c = float(self.rc["w_confirmation"])
        raw = w_s * structure + w_p * pullback + w_v * volume + w_r * reaccel + w_c * confirm

        if float(pb.get("healthy_divergence") or 0) >= 0.5:
            raw += float(self.rc["healthy_divergence_bonus"])
        if float(pb.get("structure_break") or 0) >= 0.5 or float(pb.get("big_red_volume") or 0) >= 0.5:
            raw -= float(self.rc["structure_break_penalty"])
        if negative_evidence >= 0.5:
            raw -= float(self.rc["negative_news_penalty"])
        if limit_up and str(stage).upper() == "EXTREME":
            raw *= 0.35  # still chasing — reentry not applicable same bar

        score = round(max(0.0, min(1.0, raw)), 4)
        phase = self._phase(score, pb, stage=stage, chase_score=chase_score, limit_up=limit_up)
        return {
            "reentry_score": score,
            "reentry_phase": phase,
            "reentry_components": {
                "structure_score": round(structure, 4),
                "pullback_score": round(pullback, 4),
                "volume_score": round(volume, 4),
                "reacceleration_score": round(reaccel, 4),
                "news_confirmation_score": round(confirm, 4),
            },
            "reentry_flags": {
                "healthy_divergence": float(pb.get("healthy_divergence") or 0),
                "breakout_after_pullback": float(pb.get("breakout_after_pullback") or 0),
                "structure_break": float(pb.get("structure_break") or 0),
                "high_open_low_close": float(pb.get("high_open_low_close") or 0),
                "first_non_limit_up_after_streak": float(pb.get("first_non_limit_up_after_streak") or 0),
            },
            "pullback_features": {
                k: pb.get(k)
                for k in (
                    "pullback_from_high",
                    "pullback_from_limit_up",
                    "distance_to_ma5",
                    "distance_to_ma10",
                    "distance_to_ma20",
                    "volume_ratio_to_peak",
                    "volume_contraction",
                    "turnover_normalization",
                    "drawdown_from_extreme",
                    "close_position_in_range",
                    "reclaim_ma5",
                    "reclaim_ma10",
                    "reclaim_ma20",
                    "breakout_after_pullback",
                    "reacceleration",
                    "reversal_strength",
                    "consecutive_down_days",
                    "first_non_limit_up_after_streak",
                    "limit_up_recovery",
                    "feature_as_of",
                    "available",
                )
            },
            "reentry_reason": self._reason(phase, score, pb),
        }

    def annotate_from_bars(
        self,
        feats: dict[str, Any],
        bars,
        *,
        stage: str,
        chase_score: float,
        news_score: float = 0.0,
        negative_evidence: float = 0.0,
        limit_up: bool = False,
        as_of: str | None = None,
    ) -> dict[str, Any]:
        return self.evaluate(
            feats,
            stage=stage,
            chase_score=chase_score,
            news_score=news_score,
            negative_evidence=negative_evidence,
            limit_up=limit_up,
            as_of=as_of,
            bars=bars,
        )

    def _structure_score(self, pb: dict[str, Any]) -> float:
        if float(pb.get("structure_break") or 0) >= 0.5:
            return 0.05
        s = 0.4
        if float(pb.get("distance_to_ma20") or 0) > -0.03:
            s += 0.2
        if float(pb.get("close_position_in_range") or 0) > 0.45:
            s += 0.15
        if float(pb.get("reclaim_ma5") or 0) or float(pb.get("distance_to_ma5") or 0) >= 0:
            s += 0.15
        if float(pb.get("high_open_low_close") or 0) >= 0.5:
            s -= 0.35
        return max(0.0, min(1.0, s))

    def _pullback_score(self, pb: dict[str, Any], *, stage: str) -> float:
        dd = float(pb.get("pullback_from_high") or 0)
        # Ideal healthy pullback: -2% to -8% from high
        if -0.08 <= dd <= -0.015:
            s = 0.85
        elif -0.12 <= dd < -0.08:
            s = 0.55
        elif dd > -0.015:
            # still near highs — weak pullback
            s = 0.15 if str(stage).upper() == "EXTREME" else 0.35
        else:
            s = 0.1  # deep dump
        if float(pb.get("healthy_divergence") or 0) >= 0.5:
            s = max(s, 0.8)
        if float(pb.get("consecutive_down_days") or 0) >= 4:
            s *= 0.5
        return max(0.0, min(1.0, s))

    def _volume_score(self, pb: dict[str, Any]) -> float:
        vc = float(pb.get("volume_contraction") or 0)
        vr = float(pb.get("volume_ratio_to_peak") or 1)
        tn = float(pb.get("turnover_normalization") or 0.5)
        s = 0.35 * tn + 0.45 * min(1.0, vc / 0.4) + 0.2 * (1.0 - min(1.0, vr))
        if float(pb.get("big_red_volume") or 0) >= 0.5:
            s *= 0.3
        return max(0.0, min(1.0, s))

    def _reaccel_score(self, pb: dict[str, Any]) -> float:
        s = float(pb.get("reacceleration") or 0)
        if float(pb.get("breakout_after_pullback") or 0) >= 0.5:
            s = max(s, 0.85)
        if float(pb.get("limit_up_recovery") or 0) >= 0.5:
            s = max(s, 0.7)
        if float(pb.get("reclaim_ma5") or 0) >= 0.5:
            s = max(s, 0.55)
        return max(0.0, min(1.0, s))

    def _confirmation_score(
        self,
        pb: dict[str, Any],
        *,
        news_score: float,
        negative_evidence: float,
    ) -> float:
        s = 0.5 + 0.25 * min(1.0, max(0.0, float(news_score)))
        s -= 0.5 * float(negative_evidence)
        if float(pb.get("reversal_strength") or 0) > 0.7:
            s += 0.1
        return max(0.0, min(1.0, s))

    def _phase(
        self,
        score: float,
        pb: dict[str, Any],
        *,
        stage: str,
        chase_score: float,
        limit_up: bool,
    ) -> str:
        st = str(stage).upper()
        if st == "BREAKDOWN" or float(pb.get("structure_break") or 0) >= 0.5:
            return "NONE"
        if limit_up and st == "EXTREME":
            return "WAIT"
        if score >= float(self.rc["buy_candidate_min"]) and (
            float(pb.get("reacceleration") or 0) >= 0.5 or float(pb.get("breakout_after_pullback") or 0) >= 0.5
        ):
            return "BUY_CANDIDATE"
        if float(pb.get("reacceleration") or 0) >= 0.55 or float(pb.get("breakout_after_pullback") or 0) >= 0.5:
            return "REACCELERATION"
        if float(pb.get("healthy_divergence") or 0) >= 0.5:
            return "DIVERGENCE"
        if -0.1 <= float(pb.get("pullback_from_high") or 0) <= -0.02 and float(pb.get("volume_contraction") or 0) > 0.1:
            return "PULLBACK_WATCH"
        if score >= 0.4 and float(chase_score) < 0.7:
            return "STABILIZATION"
        if st == "EXTREME":
            return "WAIT"
        return "NONE"

    def _reason(self, phase: str, score: float, pb: dict[str, Any]) -> str:
        bits = [f"phase={phase}", f"reentry={score:.2f}"]
        if float(pb.get("healthy_divergence") or 0) >= 0.5:
            bits.append("healthy_divergence")
        if float(pb.get("breakout_after_pullback") or 0) >= 0.5:
            bits.append("breakout_after_pullback")
        if float(pb.get("structure_break") or 0) >= 0.5:
            bits.append("structure_break")
        return ";".join(bits)
