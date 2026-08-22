"""V5.4 Factor attribution — wire factors/ic.py, RETIRE_CANDIDATE suggestions only."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ashare.config_loaders import load_yaml_config


def _factor_cols(cfg: dict[str, Any] | None) -> list[str]:
    weights = dict(load_yaml_config(cfg, "default").get("factors", {}).get("weights") or {})
    if weights:
        return list(weights.keys())
    return ["rs_20", "breakout", "vol_confirm", "trend", "board", "profit_gap", "event", "liquidity"]


def build_factor_attribution(
    factor_df,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run IC report + layer returns; suggest RETIRE_CANDIDATE — never auto-modify config."""
    from ashare.factors.ic import factor_ic_report, layer_returns

    cols = _factor_cols(cfg)
    if factor_df is None or getattr(factor_df, "empty", True):
        return {"available": False, "note": "no_factor_panel"}

    ic = factor_ic_report(factor_df, cols, horizons=[5, 10, 20])
    layers: dict[str, Any] = {}
    retire: list[dict[str, Any]] = []

    for col in cols:
        lr5 = layer_returns(factor_df, col, horizon=5)
        lr10 = layer_returns(factor_df, col, horizon=10)
        h10_ic = ((ic.get("h10") or {}).get(col) or {})
        ic_mean = h10_ic.get("ic_mean_spearman")
        top10 = lr10.get("top_10")
        spread = None
        if lr10.get("top_10") is not None and lr10.get("bottom_10") is not None:
            spread = float(lr10["top_10"]) - float(lr10["bottom_10"])
        layers[col] = {"layer_5": lr5, "layer_10": lr10, "ic_h10": h10_ic}
        if ic_mean is not None and abs(float(ic_mean)) < 0.02 and spread is not None and abs(spread) < 0.001:
            retire.append(
                {
                    "factor": col,
                    "ic_spearman_h10": ic_mean,
                    "t10_top_bottom_spread": spread,
                    "sample_note": h10_ic.get("n_days"),
                    "recommendation": "RETIRE_CANDIDATE",
                    "requires_human_confirm": True,
                }
            )

    return {
        "available": True,
        "ic_report": ic,
        "layers": layers,
        "retire_candidates": retire,
        "note": "RETIRE_CANDIDATE is advisory only — never auto-applied",
    }


def persist_factor_report(cfg: dict[str, Any], report: dict[str, Any]) -> Path:
    root = Path(cfg.get("_root") or Path(__file__).resolve().parents[2])
    path = root / "data" / "alpha" / "factor_report.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return path
