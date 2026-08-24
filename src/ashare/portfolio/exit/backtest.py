from __future__ import annotations

"""Exit backtest — T close signal → T+1 open fill. Gross + net. Ablation arms."""

from typing import Any

import numpy as np
import pandas as pd

from ashare.portfolio.exit.config import load_exit_config
from ashare.portfolio.exit.engine import ExitEngine
from ashare.portfolio.exit.execution import apply_net_return, round_trip_cost_rate, t1_open_fill
from ashare.portfolio.exit.labels import forward_returns
from ashare.portfolio.exit.quality import classify_exit_timing, summarize_exit_quality
from ashare.portfolio.exit.validation import summarize_giveback


ABLATION_ARMS = [
    ("no_exit", "无退出"),
    ("fixed_hold", "固定持有"),
    ("fixed_stop", "固定止盈止损"),
    ("exit_engine", "Exit Engine"),
    ("exit_wo_news", "Exit 无新闻"),
    ("exit_wo_thesis", "Exit 无 Thesis Decay"),
    ("exit_wo_momentum", "Exit 无动量"),
    ("exit_wo_trend", "Exit 无趋势"),
]


def _cost_rate(exit_cfg: dict[str, Any]) -> float:
    costs = dict((exit_cfg.get("backtest") or {}).get("costs") or {})
    return round_trip_cost_rate(
        commission_rate=float(costs.get("commission_rate", 0.00025)),
        min_commission=float(costs.get("min_commission", 5.0)),
        stamp_tax_rate=float(costs.get("stamp_tax_rate", 0.0005)),
        transfer_fee_rate=float(costs.get("transfer_fee_rate", 0.00001)),
        slippage_bps=float(costs.get("slippage_bps", 5.0)),
    )


def _cfg_with_weight_zeros(cfg: dict[str, Any] | None, zero_keys: list[str]) -> dict[str, Any]:
    base = dict(cfg or {})
    exit_cfg = load_exit_config(base)
    weights = dict(exit_cfg.get("weights") or {})
    for k in zero_keys:
        weights[k] = 0.0
    override = dict(base.get("exit") or {})
    override["weights"] = weights
    # disable thesis bump for wo_thesis
    if "thesis_decay" in zero_keys or zero_keys == ["__thesis__"]:
        override["disable_thesis_bump"] = True
    return {**base, "exit": override}


def _metrics(
    gross_returns: list[float],
    net_returns: list[float],
    holding_days: list[float],
    *,
    cost_rate: float,
    min_n: int,
) -> dict[str, Any]:
    if not gross_returns:
        return {
            "available": False,
            "status": "INSUFFICIENT_SAMPLE",
            "sample_count": 0,
            "gross": {},
            "net": {},
        }

    def _one(returns: list[float]) -> dict[str, Any]:
        s = pd.Series(returns)
        cum = (1 + s).cumprod()
        peak = cum.cummax()
        dd = (cum / peak - 1.0).min()
        vol = float(s.std()) if len(s) > 1 else 0.0
        avg_h = float(np.mean(holding_days)) if holding_days else 5.0
        sharpe = float(s.mean() / vol * np.sqrt(252 / max(avg_h, 1))) if vol > 1e-12 else None
        wins = s[s > 0]
        losses = s[s <= 0]
        pf = float(wins.sum() / abs(losses.sum())) if len(losses) and losses.sum() != 0 else None
        return {
            "total_return": float(cum.iloc[-1] - 1.0) if len(cum) else 0.0,
            "mean_return": float(s.mean()),
            "sharpe": sharpe,
            "max_drawdown": float(dd) if dd == dd else None,
            "win_rate": float((s > 0).mean()),
            "profit_factor": pf,
        }

    g = _one(gross_returns)
    n = _one(net_returns)
    n_samples = len(gross_returns)
    ok = n_samples >= min_n
    return {
        "available": ok,
        "status": "OK" if ok else "INSUFFICIENT_SAMPLE",
        "sample_count": n_samples,
        "avg_holding_days": float(np.mean(holding_days)) if holding_days else None,
        "turnover_proxy": float(n_samples),
        "cost_rate_one_way_sell": cost_rate,
        "gross": g,
        "net": n,
        # flat convenience for UI (net preferred)
        "total_return": n["total_return"] if ok else None,
        "total_return_gross": g["total_return"] if ok else None,
        "sharpe": n["sharpe"] if ok else None,
        "max_drawdown": n["max_drawdown"] if ok else None,
        "win_rate": n["win_rate"] if ok else None,
        "profit_factor": n["profit_factor"] if ok else None,
    }


def _timing_cfg(exit_cfg: dict[str, Any]) -> dict[str, float]:
    t = dict(exit_cfg.get("timing_quality") or {})
    return {
        "early_threshold": float(t.get("early_post_return", 0.03)),
        "good_threshold": float(t.get("good_post_return", -0.02)),
        "late_drawdown": float(t.get("late_drawdown", 0.12)),
        "late_mae": float(t.get("late_mae", 0.10)),
    }


def _simulate_fixed_hold(
    df: pd.DataFrame,
    i0: int,
    entry_px: float,
    hold_days: int,
    cost_rate: float,
) -> dict[str, Any]:
    """Exit at T+hold close conceptually via T+(hold-1) signal → T+hold open if possible."""
    signal_i = min(i0 + max(hold_days - 1, 0), len(df) - 1)
    fill = t1_open_fill(df, signal_i)
    if not fill.get("available"):
        # last resort for fixed schedule: if no T+1, mark unavailable path — still use last open if same bar open exists
        if fill.get("status") == "EXIT_BLOCKED":
            return {"skipped": True, "status": "EXIT_BLOCKED", "block_reason": fill.get("block_reason")}
        # EXECUTION_UNAVAILABLE at end of series — use last available open after signal if any
        if signal_i >= len(df) - 1:
            return {"skipped": True, "status": "EXECUTION_UNAVAILABLE"}
    exit_i = int(fill["fill_idx"])
    exit_px = float(fill["fill_price"])
    peak = float(df.loc[i0 : exit_i + 1, "high"].max()) if "high" in df.columns else exit_px
    trough = float(df.loc[i0 : exit_i + 1, "low"].min()) if "low" in df.columns else exit_px
    gross = exit_px / entry_px - 1.0
    net = apply_net_return(gross, cost_rate)
    max_fav = peak / entry_px - 1.0
    max_adverse = trough / entry_px - 1.0
    return {
        "skipped": False,
        "exit_i": exit_i,
        "exit_px": exit_px,
        "signal_i": signal_i,
        "gross": gross,
        "net": net,
        "hold_days": exit_i - i0,
        "giveback": max(0.0, max_fav - gross),
        "mfe": max_fav,
        "mae": max_adverse,
        "peak": peak,
        "execution": fill.get("execution") or "t1_open",
        "status": "OK",
    }


def _simulate_fixed_stop(
    df: pd.DataFrame,
    i0: int,
    entry_px: float,
    hold_days: int,
    stop_pct: float,
    take_pct: float,
    cost_rate: float,
) -> dict[str, Any]:
    max_j = min(i0 + hold_days, len(df) - 1)
    for j in range(i0 + 1, max_j + 1):
        # signal at close j-? use close j as signal day when stop hit on close
        px = float(df.loc[j, "close"])
        r = px / entry_px - 1.0
        if r <= -stop_pct or r >= take_pct:
            fill = t1_open_fill(df, j)
            if fill.get("status") == "EXIT_BLOCKED":
                continue  # try later day
            if not fill.get("available"):
                return {"skipped": True, "status": "EXECUTION_UNAVAILABLE"}
            exit_i = int(fill["fill_idx"])
            exit_px = float(fill["fill_price"])
            peak = float(df.loc[i0 : exit_i + 1, "high"].max()) if "high" in df.columns else exit_px
            trough = float(df.loc[i0 : exit_i + 1, "low"].min()) if "low" in df.columns else exit_px
            gross = exit_px / entry_px - 1.0
            return {
                "skipped": False,
                "exit_i": exit_i,
                "exit_px": exit_px,
                "signal_i": j,
                "gross": gross,
                "net": apply_net_return(gross, cost_rate),
                "hold_days": exit_i - i0,
                "giveback": max(0.0, peak / entry_px - 1.0 - gross),
                "mfe": peak / entry_px - 1.0,
                "mae": trough / entry_px - 1.0,
                "peak": peak,
                "execution": "t1_open",
                "status": "OK",
            }
    return _simulate_fixed_hold(df, i0, entry_px, hold_days, cost_rate)


def _simulate_engine(
    df: pd.DataFrame,
    i0: int,
    entry_px: float,
    hold_days: int,
    cost_rate: float,
    engine: ExitEngine,
    sym: str,
    ed,
    *,
    timing: dict[str, float],
    disable_thesis: bool = False,
    scan_step: int = 2,
) -> dict[str, Any]:
    max_j = min(i0 + max(hold_days * 2, 20), len(df) - 1)
    blocked_n = 0
    step = max(1, int(scan_step))
    for j in range(i0 + 1, max_j + 1, step):
        as_of = df.loc[j, "date"]
        hist = df.iloc[: j + 1].copy()
        peak = float(hist["high"].max()) if "high" in hist.columns else float(hist["close"].max())
        trough = float(hist["low"].min()) if "low" in hist.columns else float(hist["close"].min())
        kwargs: dict[str, Any] = {
            "symbol": sym,
            "bars": hist,
            "as_of": as_of,
            "position": {
                "symbol": sym,
                "entry_price": entry_px,
                "cost_price": entry_px,
                "entry_date": ed.isoformat() if hasattr(ed, "isoformat") else str(ed),
                "max_favorable_price": peak,
                "current_price": float(df.loc[j, "close"]),
            },
        }
        if disable_thesis:
            kwargs["buy_thesis"] = None
            kwargs["current_thesis"] = None
        sig = engine.evaluate(**kwargs)
        score = float(sig.get("exit_score") or 0)
        if sig.get("action") in {"EXIT", "REDUCE"} and score >= 0.6:
            fill = t1_open_fill(df, j)
            if fill.get("status") == "EXIT_BLOCKED":
                blocked_n += 1
                continue
            if not fill.get("available"):
                # cannot silently use T close
                continue
            exit_i = int(fill["fill_idx"])
            exit_px = float(fill["fill_price"])
            gross = exit_px / entry_px - 1.0
            # post-exit returns from fill date
            fr = forward_returns(df, signal_date=df.loc[exit_i, "date"], horizons=[1, 5, 10], entry_price=exit_px)
            post1 = (fr.get("1") or {}).get("return") if (fr.get("1") or {}).get("available") else None
            post5 = (fr.get("5") or {}).get("return") if (fr.get("5") or {}).get("available") else None
            post10 = (fr.get("10") or {}).get("return") if (fr.get("10") or {}).get("available") else None
            dd = (peak - float(df.loc[j, "close"])) / peak if peak else None
            mae = trough / entry_px - 1.0
            q = classify_exit_timing(
                exit_price=exit_px,
                peak_before_exit=peak,
                post_return_1d=post1,
                post_return_5d=post5,
                post_return_10d=post10,
                drawdown_at_exit=dd,
                mae=mae,
                **timing,
            )
            return {
                "skipped": False,
                "exit_i": exit_i,
                "exit_px": exit_px,
                "signal_i": j,
                "gross": gross,
                "net": apply_net_return(gross, cost_rate),
                "hold_days": exit_i - i0,
                "giveback": max(0.0, peak / entry_px - 1.0 - gross),
                "mfe": peak / entry_px - 1.0,
                "mae": mae,
                "peak": peak,
                "quality": q,
                "exit_score": score,
                "execution": "t1_open",
                "status": "OK",
                "exit_blocked_attempts": blocked_n,
            }
    # fallback fixed hold schedule
    fb = _simulate_fixed_hold(df, i0, entry_px, hold_days, cost_rate)
    fb["exit_blocked_attempts"] = blocked_n
    return fb


def run_exit_backtest(
    bars_by_symbol: dict[str, pd.DataFrame],
    entries: list[dict[str, Any]],
    *,
    cfg: dict[str, Any] | None = None,
    minimum_sample: int | None = None,
) -> dict[str, Any]:
    """
    entries: [{symbol, entry_date, entry_price?}]
    Execution: T close signal → T+1 open. Never silent T-close fill.
    """
    exit_cfg = load_exit_config(cfg)
    bt = dict(exit_cfg.get("backtest") or {})
    min_n = int(minimum_sample or exit_cfg.get("minimum_sample") or 30)
    hold_days = int(bt.get("fixed_hold_days", 10))
    stop_pct = float(bt.get("fixed_stop_pct", 0.08))
    take_pct = float(bt.get("fixed_take_pct", 0.15))
    cost_rate = _cost_rate(exit_cfg)
    timing = _timing_cfg(exit_cfg)
    scan_step = int(bt.get("scan_step") or 2)

    engines: dict[str, ExitEngine] = {
        "exit_engine": ExitEngine(cfg),
        "exit_wo_news": ExitEngine(_cfg_with_weight_zeros(cfg, ["news_reversal"])),
        "exit_wo_momentum": ExitEngine(
            _cfg_with_weight_zeros(cfg, ["momentum_decay", "volume_distribution"])
        ),
        "exit_wo_trend": ExitEngine(
            _cfg_with_weight_zeros(
                cfg, ["trend_decay", "moving_average_break", "relative_strength_decay"]
            )
        ),
        "exit_wo_thesis": ExitEngine(_cfg_with_weight_zeros(cfg, ["__thesis__"])),
    }

    buckets: dict[str, dict[str, list]] = {
        key: {"gross": [], "net": [], "holds": [], "givebacks": [], "quality": [], "blocked": 0, "exec_fail": 0}
        for key, _ in ABLATION_ARMS
    }

    # Cache identical (symbol, entry_date, entry_price) paths — avoids O(n) duplicate work
    path_cache: dict[tuple, dict[str, dict[str, Any]]] = {}

    for e in entries:
        sym = str(e.get("symbol") or "")
        bars = bars_by_symbol.get(sym)
        if bars is None or (hasattr(bars, "empty") and bars.empty):
            continue
        df = bars.copy()
        df["date"] = pd.to_datetime(df["date"]).dt.date
        df = df.sort_values("date").reset_index(drop=True)
        try:
            ed = pd.Timestamp(e["entry_date"]).date()
        except Exception:  # noqa: BLE001
            continue
        idx = df.index[df["date"] >= ed]
        if len(idx) == 0:
            continue
        i0 = int(idx[0])
        entry_px = float(e.get("entry_price") or df.loc[i0, "close"])
        cache_key = (sym, str(ed), round(entry_px, 4))

        if cache_key not in path_cache:
            sims: dict[str, dict[str, Any]] = {}
            for arm in ("no_exit", "fixed_hold"):
                sims[arm] = _simulate_fixed_hold(df, i0, entry_px, hold_days, cost_rate)
            sims["fixed_stop"] = _simulate_fixed_stop(
                df, i0, entry_px, hold_days, stop_pct, take_pct, cost_rate
            )
            for arm, eng in engines.items():
                sims[arm] = _simulate_engine(
                    df,
                    i0,
                    entry_px,
                    hold_days,
                    cost_rate,
                    eng,
                    sym,
                    ed,
                    timing=timing,
                    disable_thesis=(arm == "exit_wo_thesis"),
                    scan_step=scan_step,
                )
            path_cache[cache_key] = sims

        sims = path_cache[cache_key]
        for arm, _ in ABLATION_ARMS:
            _record(buckets[arm], sims[arm])

    strategies = {}
    for key, label in ABLATION_ARMS:
        block = buckets[key]
        m = _metrics(block["gross"], block["net"], block["holds"], cost_rate=cost_rate, min_n=min_n)
        gb = summarize_giveback(block["givebacks"], minimum_sample=min_n)
        m["giveback"] = gb
        m["mean_giveback"] = gb.get("mean")
        m["median_giveback"] = gb.get("median")
        m["p90_giveback"] = gb.get("p90")
        m["label"] = label
        m["exit_blocked"] = block["blocked"]
        m["execution_unavailable"] = block["exec_fail"]
        if key.startswith("exit"):
            m["exit_quality"] = summarize_exit_quality(block["quality"], minimum_sample=min_n)
        strategies[key] = m

    return {
        "minimum_sample": min_n,
        "n_entries": len(entries),
        "execution_model": "t1_open",
        "cost_rate_one_way_sell": cost_rate,
        "strategies": strategies,
        "ablation_arms": [{"id": k, "label": lab} for k, lab in ABLATION_ARMS],
        "note": "T close signal → T+1 open fill. Gross and net (commission/stamp/transfer/slippage). EXIT_BLOCKED never assumed filled.",
        "versions": {"exit_version": exit_cfg.get("version")},
    }


def _record(bucket: dict[str, Any], sim: dict[str, Any]) -> None:
    if sim.get("skipped"):
        st = sim.get("status")
        if st == "EXIT_BLOCKED":
            bucket["blocked"] += 1
        elif st == "EXECUTION_UNAVAILABLE":
            bucket["exec_fail"] += 1
        return
    bucket["gross"].append(float(sim["gross"]))
    bucket["net"].append(float(sim["net"]))
    bucket["holds"].append(float(sim["hold_days"]))
    bucket["givebacks"].append(float(sim["giveback"]))
    if sim.get("quality"):
        bucket["quality"].append(sim["quality"])
    bucket["blocked"] += int(sim.get("exit_blocked_attempts") or 0)
