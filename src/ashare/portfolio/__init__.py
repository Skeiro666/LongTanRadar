from __future__ import annotations

from typing import Any

import numpy as np

from ashare.config_loaders import load_yaml_config


class PortfolioEngine:
    """Position suggestions from scores — RiskEngine still final gate."""

    def __init__(self, cfg: dict[str, Any] | None = None) -> None:
        self.cfg = cfg or {}
        self.models = load_yaml_config(self.cfg, "models")
        self.pos = dict(self.models.get("position") or {})
        self.rules = dict(self.models.get("signal_rules") or {})
        self.final_w = dict(self.models.get("final_score_weights") or {})

    def final_score(self, row: dict[str, Any]) -> float:
        w = self.final_w
        # expect already z-scored components when possible
        ml = float(row.get("ml_z") or row.get("ml_prediction") or 0)
        # raw ml_prediction is return scale — treat small
        if "ml_z" not in row and row.get("ml_prediction") is not None:
            ml = float(row["ml_prediction"]) * 20.0  # soft scale
        leader = float(row.get("leader_z") or row.get("leader_score") or 0)
        mom = float(row.get("momentum_z") or row.get("score_momentum") or 0)
        qual = float(row.get("quality_z") or row.get("score_quality") or 0)
        val = float(row.get("value_z") or row.get("score_value") or 0)
        return (
            float(w.get("ml", 0.4)) * ml
            + float(w.get("leader", 0.3)) * leader
            + float(w.get("momentum", 0.15)) * mom
            + float(w.get("quality", 0.1)) * qual
            + float(w.get("value", 0.05)) * val
        )

    def signal_alignment(self, row: dict[str, Any]) -> dict[str, Any]:
        ml = float(row.get("ml_z") or (float(row.get("ml_prediction") or 0) * 20))
        leader = float(row.get("leader_z") or row.get("leader_score") or 0)
        mom = float(row.get("momentum_z") or row.get("score_momentum") or 0)
        rules = self.rules
        sb = rules.get("strong_buy") or {}
        sn = rules.get("strong_negative") or {}
        if ml < float(sn.get("ml_z_lt", -1)) and leader < float(sn.get("leader_z_lt", -1)):
            return {"state": "strong_negative", "scale": 0.0, "allow_buy": False}
        if ml < 0 and leader < 0 and mom < 0:
            return {"state": "strong_negative", "scale": 0.0, "allow_buy": False}
        if (
            ml > float(sb.get("ml_z_gt", 1))
            and leader > float(sb.get("leader_z_gt", 1))
            and mom > float(sb.get("momentum_z_gt", 0.5))
        ):
            return {"state": "strong_buy", "scale": 1.0, "allow_buy": True}
        if ml < 0 and leader > 0:
            return {"state": "conflict", "scale": float(rules.get("conflict_max_scale", 0.5)), "allow_buy": True}
        nb = rules.get("normal_buy") or {}
        if ml > float(nb.get("ml_z_gt", 0)) and leader > float(nb.get("leader_z_gt", 0)):
            return {"state": "normal_buy", "scale": 1.0, "allow_buy": True}
        return {"state": "neutral", "scale": 0.25, "allow_buy": False}

    def suggest_weights(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        max_name = float(self.pos.get("max_name_weight", 0.10))
        max_gross = float(self.pos.get("max_gross_weight", 0.95))
        out = []
        raw_w = []
        for r in rows:
            fs = self.final_score(r)
            align = self.signal_alignment(r)
            vol = float((r.get("factors") or {}).get("volatility_20d") or r.get("volatility_20d") or 0.02)
            vol_pen = 1.0 / (1.0 + max(vol, 0.0) * 10)
            conf = float((r.get("chairman") or {}).get("confidence") or r.get("confidence") or 0.5)
            if not align["allow_buy"]:
                w = 0.0
            else:
                w = max(0.0, fs) * align["scale"] * vol_pen * conf
            item = {**r, "final_score": fs, "signal_alignment": align, "raw_weight": w}
            out.append(item)
            raw_w.append(w)
        s = sum(raw_w) or 1.0
        for item in out:
            w = min(max_name, item["raw_weight"] / s)
            item["target_weight"] = w
        gross = sum(i["target_weight"] for i in out)
        if gross > max_gross and gross > 0:
            scale = max_gross / gross
            for i in out:
                i["target_weight"] *= scale
        return out


class RiskFilterEngine:
    """Pre-trade filters beyond RiskGuard caps."""

    def __init__(self, cfg: dict[str, Any] | None = None) -> None:
        self.cfg = cfg or {}

    def allow_open(self, bar_like: dict[str, Any]) -> tuple[bool, str]:
        if bar_like.get("is_st"):
            return False, "st"
        if bar_like.get("is_halt"):
            return False, "halt"
        if bar_like.get("limit_up"):
            return False, "limit_up"
        amt = float(bar_like.get("amount") or 0)
        if amt and amt < float((self.cfg.get("pool") or {}).get("min_amount") or 0):
            return False, "liquidity"
        vol = float((bar_like.get("factors") or {}).get("volatility_20d") or 0)
        if vol > 0.12:
            return False, "extreme_vol"
        return True, "ok"


def market_regime(index_closes: list[float] | None = None, panel_mom20: list[float] | None = None) -> str:
    """Simple regime from universe momentum/vol proxies."""
    if panel_mom20:
        m = float(np.nanmean(panel_mom20))
        v = float(np.nanstd(panel_mom20) or 0)
        if v > 0.08:
            return "HIGH_VOLATILITY"
        if m > 0.03:
            return "BULL"
        if m < -0.03:
            return "BEAR"
        return "SIDEWAYS"
    if index_closes and len(index_closes) >= 60:
        c = np.array(index_closes, dtype=float)
        mom = c[-1] / c[-60] - 1
        rets = np.diff(c[-21:]) / c[-21:-1]
        vol = float(np.std(rets))
        if vol > 0.02:
            return "HIGH_VOLATILITY"
        if mom > 0.05:
            return "BULL"
        if mom < -0.05:
            return "BEAR"
        return "SIDEWAYS"
    return "UNKNOWN"
