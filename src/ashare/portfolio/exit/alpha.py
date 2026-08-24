from __future__ import annotations

"""Exit Alpha — compare strategies including ablation; no fabricated returns."""

from typing import Any

from ashare.portfolio.exit.backtest import ABLATION_ARMS, run_exit_backtest
from ashare.portfolio.exit.config import load_exit_config


def build_exit_alpha(
    bars_by_symbol: dict,
    entries: list[dict[str, Any]],
    *,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    exit_cfg = load_exit_config(cfg)
    min_n = int(exit_cfg.get("minimum_sample") or 30)
    bt = run_exit_backtest(bars_by_symbol, entries, cfg=cfg, minimum_sample=min_n)
    strats = bt.get("strategies") or {}

    def _row(key: str, label: str) -> dict[str, Any]:
        s = strats.get(key) or {}
        insuf = s.get("status") == "INSUFFICIENT_SAMPLE" or not s.get("available")
        return {
            "id": key,
            "label": label,
            "sample_count": s.get("sample_count") or 0,
            "status": "INSUFFICIENT_SAMPLE" if insuf else s.get("status") or "OK",
            "total_return": None if insuf else s.get("total_return"),
            "total_return_gross": None if insuf else s.get("total_return_gross"),
            "sharpe": None if insuf else s.get("sharpe"),
            "max_drawdown": None if insuf else s.get("max_drawdown"),
            "win_rate": None if insuf else s.get("win_rate"),
            "profit_factor": None if insuf else s.get("profit_factor"),
            "avg_holding_days": None if insuf else s.get("avg_holding_days"),
            "turnover_proxy": None if insuf else s.get("turnover_proxy"),
            "mean_giveback": None if insuf else s.get("mean_giveback"),
            "median_giveback": None if insuf else s.get("median_giveback"),
            "p90_giveback": None if insuf else s.get("p90_giveback"),
            "giveback": s.get("giveback"),
            "exit_quality": s.get("exit_quality"),
            "exit_blocked": s.get("exit_blocked"),
            "execution_unavailable": s.get("execution_unavailable"),
            "gross": s.get("gross"),
            "net": s.get("net"),
        }

    label_map = {k: lab for k, lab in ABLATION_ARMS}
    rows = [_row(k, label_map.get(k, k)) for k, _ in ABLATION_ARMS]

    base = strats.get("no_exit") or {}
    fixed = strats.get("fixed_stop") or {}
    for r in rows:
        if r["id"] == "no_exit" or r["status"] == "INSUFFICIENT_SAMPLE":
            r["delta_return_vs_no_exit"] = None
            r["delta_giveback_vs_no_exit"] = None
            r["delta_return_vs_fixed_stop"] = None
            continue
        br = base.get("total_return")
        if br is None or r.get("total_return") is None or base.get("status") == "INSUFFICIENT_SAMPLE":
            r["delta_return_vs_no_exit"] = None
        else:
            r["delta_return_vs_no_exit"] = round(float(r["total_return"]) - float(br), 6)
        bg = base.get("mean_giveback")
        if bg is not None and r.get("mean_giveback") is not None:
            r["delta_giveback_vs_no_exit"] = round(float(bg) - float(r["mean_giveback"]), 6)
        else:
            r["delta_giveback_vs_no_exit"] = None
        fr = fixed.get("total_return")
        if fr is not None and r.get("total_return") is not None and fixed.get("status") != "INSUFFICIENT_SAMPLE":
            r["delta_return_vs_fixed_stop"] = round(float(r["total_return"]) - float(fr), 6)
        else:
            r["delta_return_vs_fixed_stop"] = None

    return {
        "available": any(r["sample_count"] > 0 for r in rows),
        "minimum_sample": min_n,
        "strategies": rows,
        "backtest": bt,
        "execution_model": bt.get("execution_model"),
        "note": bt.get("note"),
    }
