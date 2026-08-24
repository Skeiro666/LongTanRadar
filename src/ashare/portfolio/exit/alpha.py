from __future__ import annotations

"""Exit Alpha — compare strategies; no fabricated returns when sample low."""

from typing import Any

from ashare.portfolio.exit.backtest import run_exit_backtest
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
            "sharpe": None if insuf else s.get("sharpe"),
            "max_drawdown": None if insuf else s.get("max_drawdown"),
            "win_rate": None if insuf else s.get("win_rate"),
            "profit_factor": None if insuf else s.get("profit_factor"),
            "avg_holding_days": None if insuf else s.get("avg_holding_days"),
            "mean_giveback": None if insuf else s.get("mean_giveback"),
            "exit_quality": s.get("exit_quality"),
        }

    rows = [
        _row("no_exit", "无退出（固定持有）"),
        _row("fixed_stop", "固定止盈止损"),
        _row("exit_engine", "Exit Engine"),
    ]
    # deltas vs no_exit
    base = strats.get("no_exit") or {}
    for r in rows:
        if r["id"] == "no_exit" or r["status"] == "INSUFFICIENT_SAMPLE":
            r["delta_return_vs_no_exit"] = None
            continue
        br = base.get("total_return")
        if br is None or r.get("total_return") is None or base.get("status") == "INSUFFICIENT_SAMPLE":
            r["delta_return_vs_no_exit"] = None
        else:
            r["delta_return_vs_no_exit"] = round(float(r["total_return"]) - float(br), 6)

    return {
        "available": any(r["sample_count"] > 0 for r in rows),
        "minimum_sample": min_n,
        "strategies": rows,
        "backtest": bt,
    }
