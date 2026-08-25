"""
Entry Return Distribution Lab (research-only).

No LLM. No BUY threshold changes. No ML.
Reuses cached daily bars + entry_validation samples.
Future returns / MFE / MAE / LD are labels only.
"""
from __future__ import annotations

import json
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ashare.leader.entry_validation import (
    ENTRY_MODES,
    HORIZONS,
    MIN_SAMPLE,
    MIN_SAMPLE_SOFT,
)
from ashare.leader.features import compute_leader_features
from ashare.leader.pullback_features import compute_pullback_features

FOCUS_MODES = ("DIRECT_CHASE", "FIRST_DIVERGENCE", "PULLBACK", "REACCELERATION")


def _cost_cfg(cfg: dict[str, Any] | None) -> dict[str, float]:
    costs = dict((cfg or {}).get("costs") or {})
    return {
        "commission_rate": float(costs.get("commission_rate", 0.00025)),
        "min_commission": float(costs.get("min_commission", 5.0)),
        "stamp_tax_rate": float(costs.get("stamp_tax_rate", 0.0005)),
        "transfer_fee_rate": float(costs.get("transfer_fee_rate", 0.00001)),
        "slippage_bps": float(costs.get("slippage_bps", 5.0)),
        "notional": 10_000.0,
    }


def round_trip_cost_buy_sell(cfg: dict[str, Any] | None = None) -> float:
    """Full round-trip: buy + sell fees/slip + stamp on sell."""
    c = _cost_cfg(cfg)
    n = c["notional"]
    buy_comm = max(n * c["commission_rate"], c["min_commission"]) / n
    sell_comm = max(n * c["commission_rate"], c["min_commission"]) / n
    slip = 2.0 * (c["slippage_bps"] / 10_000.0)
    transfer = 2.0 * c["transfer_fee_rate"]
    stamp = c["stamp_tax_rate"]
    return float(buy_comm + sell_comm + slip + transfer + stamp)


def _board_bucket(b: int) -> str:
    if b <= 1:
        return "1"
    if b >= 6:
        return "6+"
    return str(int(b))


def _pullback_depth_bucket(dd: float | None) -> str | None:
    if dd is None:
        return None
    x = float(dd)
    if x > -0.03:
        return "0~-3%"
    if x > -0.07:
        return "-3%~-7%"
    return "-7%+"


def _hist_bins(arr: np.ndarray, edges: list[float] | None = None) -> dict[str, int]:
    if edges is None:
        edges = [-0.20, -0.10, -0.05, 0.0, 0.05, 0.10, 0.20]
    labs = [f"<{edges[0]:.0%}"]
    for i in range(len(edges) - 1):
        labs.append(f"{edges[i]:.0%}~{edges[i+1]:.0%}")
    labs.append(f">={edges[-1]:.0%}")
    counts = {lab: 0 for lab in labs}
    for v in arr:
        placed = False
        if v < edges[0]:
            counts[labs[0]] += 1
            placed = True
        elif v >= edges[-1]:
            counts[labs[-1]] += 1
            placed = True
        else:
            for i in range(len(edges) - 1):
                if edges[i] <= v < edges[i + 1]:
                    counts[labs[i + 1]] += 1
                    placed = True
                    break
        if not placed:
            counts[labs[-1]] += 1
    return counts


def distribution_stats(returns: list[float | None], *, extras: dict[str, Any] | None = None) -> dict[str, Any]:
    vals = [float(x) for x in returns if x is not None and not (isinstance(x, float) and np.isnan(x))]
    n = len(vals)
    out: dict[str, Any] = {"n": n}
    if n < MIN_SAMPLE_SOFT:
        out["status"] = "INSUFFICIENT_SAMPLE"
        return out
    out["status"] = "OK" if n >= MIN_SAMPLE else "LOW_SAMPLE"
    arr = np.array(vals, dtype=float)
    out.update(
        {
            "mean": float(arr.mean()),
            "median": float(np.median(arr)),
            "std": float(arr.std(ddof=1)) if n > 1 else 0.0,
            "p10": float(np.percentile(arr, 10)),
            "p25": float(np.percentile(arr, 25)),
            "p50": float(np.percentile(arr, 50)),
            "p75": float(np.percentile(arr, 75)),
            "p90": float(np.percentile(arr, 90)),
            "best": float(arr.max()),
            "worst": float(arr.min()),
            "positive_return_rate": float((arr > 0).mean()),
            "return_gt_5": float((arr > 0.05).mean()),
            "return_gt_10": float((arr > 0.10).mean()),
            "return_gt_20": float((arr > 0.20).mean()),
            "return_lt_-5": float((arr < -0.05).mean()),
            "return_lt_-10": float((arr < -0.10).mean()),
            "return_lt_-20": float((arr < -0.20).mean()),
            "histogram": _hist_bins(arr),
        }
    )
    # winner concentration: share of total positive PnL from top 10% of all samples
    pos = arr[arr > 0]
    if len(pos) and pos.sum() > 0:
        k = max(1, int(np.ceil(0.1 * n)))
        top = np.sort(arr)[::-1][:k]
        top_pos = top[top > 0].sum()
        out["top10pct_share_of_positive_pnl"] = float(top_pos / pos.sum())
        out["top10pct_share_of_total_pnl"] = float(top.sum() / arr.sum()) if arr.sum() != 0 else None
        # how many winners account for 50% of positive mass
        ordered = np.sort(pos)[::-1]
        cum = np.cumsum(ordered) / ordered.sum()
        out["winners_for_half_profit_frac"] = float((cum >= 0.5).argmax() + 1) / len(ordered)
    else:
        out["top10pct_share_of_positive_pnl"] = None
        out["top10pct_share_of_total_pnl"] = None
        out["winners_for_half_profit_frac"] = None
    if extras:
        out.update(extras)
    return out


def expected_value_pack(returns: list[float | None], *, cost_rate: float = 0.0) -> dict[str, Any]:
    vals = [float(x) for x in returns if x is not None]
    if len(vals) < MIN_SAMPLE_SOFT:
        return {"status": "INSUFFICIENT_SAMPLE", "n": len(vals)}
    arr = np.array(vals, dtype=float)
    net = arr - cost_rate
    wins = net[net > 0]
    losses = net[net <= 0]
    win_p = float((net > 0).mean())
    loss_p = 1.0 - win_p
    avg_win = float(wins.mean()) if len(wins) else 0.0
    avg_loss = float(abs(losses.mean())) if len(losses) else 0.0
    ev = win_p * avg_win - loss_p * avg_loss
    profit_factor = float(wins.sum() / abs(losses.sum())) if len(losses) and abs(losses.sum()) > 1e-12 else None
    payoff = float(avg_win / avg_loss) if avg_loss > 1e-12 else None
    downside = net[net < 0]
    down_dev = float(np.sqrt((downside**2).mean())) if len(downside) else 0.0
    sortino = float(net.mean() / down_dev) if down_dev > 1e-12 else None
    return {
        "status": "OK" if len(vals) >= MIN_SAMPLE else "LOW_SAMPLE",
        "n": len(vals),
        "gross_mean": float(arr.mean()),
        "net_mean": float(net.mean()),
        "cost_rate": cost_rate,
        "win_probability": win_p,
        "loss_probability": loss_p,
        "average_win": avg_win,
        "average_loss": avg_loss,
        "ev": ev,
        "profit_factor": profit_factor,
        "payoff_ratio": payoff,
        "downside_deviation": down_dev,
        "sortino_like": sortino,
        "expected_return_after_cost": float(net.mean()),
    }


def risk_adjusted_return(
    mean_ret: float | None,
    ld_rate: float | None,
    mdd: float | None,
    *,
    lambda_ld: float = 0.35,
    lambda_dd: float = 0.50,
) -> float | None:
    if mean_ret is None:
        return None
    ld = float(ld_rate or 0)
    dd = abs(float(mdd or 0))
    return float(mean_ret - lambda_ld * ld - lambda_dd * dd)


def classify_pullback_health(row: dict[str, Any]) -> str:
    """As-of feature labels only (research)."""
    sb = float(row.get("structure_break") or 0)
    vc = float(row.get("volume_contraction") or 0)
    br = float(row.get("big_red_volume") or 0)
    holc = float(row.get("high_open_low_close") or 0)
    cd = float(row.get("consecutive_down_days") or 0)
    vr = float(row.get("volume_ratio_to_peak") or 0)
    if sb >= 0.5 or br >= 0.5 or holc >= 0.5 or cd >= 3 or (vr >= 0.85 and float(row.get("pullback_from_high") or 0) < -0.05):
        return "DANGEROUS_PULLBACK"
    if sb < 0.5 and vc > 0.08 and br < 0.5 and holc < 0.5 and cd < 3:
        return "HEALTHY_PULLBACK"
    return "NEUTRAL_PULLBACK"


def entry_quality_research(row: dict[str, Any]) -> float:
    """
    Research-only quality from as-of features. NOT for BUY pipeline.
    Higher = healthier risk release structure (heuristic, uncalibrated).
    """
    s = 0.35 * float(row.get("structure_score") or 0)
    s += 0.25 * float(row.get("pullback_score") or 0)
    s += 0.20 * float(row.get("volume_score") or 0)
    s += 0.10 * min(1.0, max(0.0, -float(row.get("pullback_from_high") or 0) / 0.07))
    s += 0.10 * float(row.get("volume_contraction") or 0)
    if float(row.get("structure_break") or 0) >= 0.5:
        s *= 0.2
    if float(row.get("big_red_volume") or 0) >= 0.5:
        s *= 0.4
    return round(max(0.0, min(1.0, s)), 4)


def risk_adjusted_entry_score_research(
    row: dict[str, Any],
    *,
    lambda_ld: float = 0.35,
    lambda_dd: float = 0.50,
) -> dict[str, Any]:
    """
    Research-only ex-post diagnostic using labels — NEVER feed into live BUY.
    Documented as research label, not a tradable signal.
    """
    lab = row.get("labels") or {}
    t5 = lab.get("t+5")
    ld = lab.get("t+5_limit_down")
    mdd = lab.get("t+5_mdd") if lab.get("t+5_mdd") is not None else lab.get("max_drawdown")
    if t5 is None:
        return {"risk_adjusted_entry_score": None, "research_only": True, "uses_future_labels": True}
    score = risk_adjusted_return(
        float(t5),
        1.0 if ld else 0.0,
        float(mdd) if mdd is not None else 0.0,
        lambda_ld=lambda_ld,
        lambda_dd=lambda_dd,
    )
    return {
        "risk_adjusted_entry_score": score,
        "research_only": True,
        "uses_future_labels": True,
        "note": "Ex-post diagnostic only; must not enter BUY pipeline.",
    }


def enrich_sample_from_bars(
    row: dict[str, Any],
    df: pd.DataFrame,
    *,
    cost_rate: float,
) -> dict[str, Any]:
    """Attach as-of pullback features + T+1 open gross/net labels."""
    out = dict(row)
    frame = df.copy()
    frame["date"] = pd.to_datetime(frame["date"])
    frame = frame.sort_values("date").reset_index(drop=True)
    dates = frame["date"].dt.normalize()
    target = pd.Timestamp(row["date"]).normalize()
    hits = np.where(dates == target)[0]
    if len(hits) == 0:
        return out
    i = int(hits[0])
    hist = frame.iloc[: i + 1]
    feats = compute_leader_features(hist, as_of=row["date"])
    pb = compute_pullback_features(hist, as_of=row["date"], base_feats=feats or {})
    out["pullback_from_high"] = pb.get("pullback_from_high")
    out["pullback_from_limit_up"] = pb.get("pullback_from_limit_up")
    out["volume_contraction"] = pb.get("volume_contraction")
    out["volume_ratio_to_peak"] = pb.get("volume_ratio_to_peak")
    out["structure_break"] = pb.get("structure_break")
    out["big_red_volume"] = pb.get("big_red_volume")
    out["high_open_low_close"] = pb.get("high_open_low_close")
    out["consecutive_down_days"] = pb.get("consecutive_down_days")
    out["healthy_divergence"] = pb.get("healthy_divergence")
    out["pullback_depth_bucket"] = _pullback_depth_bucket(pb.get("pullback_from_high"))
    out["pullback_health"] = classify_pullback_health(out)
    out["entry_quality"] = entry_quality_research(out)
    out["reentry_score_status"] = "REENTRY_SCORE_UNCALIBRATED"
    out["board_bucket"] = _board_bucket(int(row.get("board_count") or 0))

    # T+1 open fill labels
    c = frame["close"].astype(float).values
    o = frame["open"].astype(float).values if "open" in frame.columns else c
    ld = frame["limit_down"].astype(bool).values if "limit_down" in frame.columns else np.zeros(len(frame), dtype=bool)
    labels = dict(out.get("labels") or {})
    if i + 1 < len(frame):
        entry = float(o[i + 1])
        labels["entry_fill"] = "T+1_open"
        labels["entry_price"] = entry
        for h in HORIZONS:
            j = i + h
            # exit at close of day i+h (holding h days after signal; fill next open)
            # If h=1: buy open T+1, sell close T+1
            exit_i = i + h
            if exit_i >= len(c) or entry <= 0:
                labels[f"t+{h}_gross_t1open"] = None
                labels[f"t+{h}_net_t1open"] = None
                continue
            gross = float(c[exit_i] / entry - 1.0)
            labels[f"t+{h}_gross_t1open"] = gross
            labels[f"t+{h}_net_t1open"] = float(gross - cost_rate)
            labels[f"t+{h}_limit_down_t1"] = bool(ld[i + 1 : exit_i + 1].any())
    out["labels"] = labels
    out.update(risk_adjusted_entry_score_research(out))
    return out


def load_or_build_rows(root: Path, cfg: dict[str, Any] | None, *, max_symbols: int = 120) -> list[dict[str, Any]]:
    samples_path = root / "data" / "leader" / "entry_validation_samples.jsonl"
    rows: list[dict[str, Any]] = []
    if samples_path.exists():
        for line in samples_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
    if not rows:
        # rebuild light
        from ashare.leader.entry_validation import run_entry_validation

        run_entry_validation(root=root, max_symbols=max_symbols, cfg=cfg)
        for line in samples_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
    return rows


def tag_reaccel_paths(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_sym: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_sym[r["symbol"]].append(r)
    for sym, lst in by_sym.items():
        lst.sort(key=lambda x: x["date"])
        for i, r in enumerate(lst):
            if r.get("entry_mode") != "REACCELERATION":
                r["reaccel_path"] = "NA"
                continue
            prior = lst[:i]
            window = [p for p in prior if p["date"] >= _date_minus(r["date"], 15)]
            modes = {p["entry_mode"] for p in window}
            if "PULLBACK" in modes:
                r["reaccel_path"] = "AFTER_PULLBACK"
            elif "FIRST_DIVERGENCE" in modes:
                r["reaccel_path"] = "AFTER_DIVERGENCE"
            elif r.get("had_extreme_recently") or r.get("stage") == "EXTREME":
                r["reaccel_path"] = "AFTER_EXTREME"
            else:
                r["reaccel_path"] = "DIRECT_REACCEL"
            r["structure_repaired"] = float(r.get("structure_score") or 0) >= 0.55 and float(r.get("structure_break") or 0) < 0.5
    return rows


def _date_minus(date_s: str, days: int) -> str:
    return str((pd.Timestamp(date_s) - pd.Timedelta(days=days)).date())


def _rets(rows: list[dict[str, Any]], key: str) -> list[float | None]:
    return [(r.get("labels") or {}).get(key) for r in rows]


def _ld_rate(rows: list[dict[str, Any]], key: str = "t+5_limit_down") -> float | None:
    vals = [(r.get("labels") or {}).get(key) for r in rows]
    vals = [bool(v) for v in vals if v is not None]
    return float(np.mean(vals)) if vals else None


def _mdd_mean(rows: list[dict[str, Any]], key: str = "t+5_mdd") -> float | None:
    vals = []
    for r in rows:
        lab = r.get("labels") or {}
        v = lab.get(key)
        if v is None:
            v = lab.get("max_drawdown")
        if v is not None:
            vals.append(float(v))
    return float(np.mean(vals)) if vals else None


def cell_summary(rows: list[dict[str, Any]], *, cost_rate: float, lambda_ld: float = 0.35, lambda_dd: float = 0.50) -> dict[str, Any]:
    n = len(rows)
    if n < MIN_SAMPLE_SOFT:
        return {"n": n, "status": "INSUFFICIENT_SAMPLE"}
    status = "OK" if n >= MIN_SAMPLE else "LOW_SAMPLE"
    dist = {f"t+{h}": distribution_stats(_rets(rows, f"t+{h}")) for h in HORIZONS}
    ev = {f"t+{h}": expected_value_pack(_rets(rows, f"t+{h}"), cost_rate=0.0) for h in HORIZONS}
    ev_net = {f"t+{h}": expected_value_pack(_rets(rows, f"t+{h}_gross_t1open"), cost_rate=cost_rate) for h in HORIZONS}
    t5 = dist.get("t+5") or {}
    ld = _ld_rate(rows)
    mdd = _mdd_mean(rows)
    mae = [float((r.get("labels") or {}).get("mae")) for r in rows if (r.get("labels") or {}).get("mae") is not None]
    rar = risk_adjusted_return(t5.get("mean"), ld, mdd, lambda_ld=lambda_ld, lambda_dd=lambda_dd)
    return {
        "n": n,
        "status": status,
        "mean_return": t5.get("mean"),
        "median_return": t5.get("median"),
        "win_rate": t5.get("positive_return_rate"),
        "limit_down_rate": ld,
        "MDD": mdd,
        "MAE_mean": float(np.mean(mae)) if mae else None,
        "risk_adjusted_return": rar,
        "distribution": dist,
        "ev_close_to_close": ev,
        "ev_t1open_net": ev_net,
        "winner_concentration": {
            "top10pct_share_of_positive_pnl": t5.get("top10pct_share_of_positive_pnl"),
            "winners_for_half_profit_frac": t5.get("winners_for_half_profit_frac"),
            "mean_minus_median": (t5.get("mean") - t5.get("median")) if t5.get("mean") is not None and t5.get("median") is not None else None,
        },
    }


def good_entry_gate(cell: dict[str, Any]) -> dict[str, Any]:
    """Strict research definition of a 'good entry' — not for auto BUY."""
    checks = {
        "positive_ev": (cell.get("mean_return") or -1) > 0,
        "win_rate_ok": (cell.get("win_rate") or 0) >= 0.45,
        "ld_ok": (cell.get("limit_down_rate") or 1) <= 0.20,
        "mae_ok": (cell.get("MAE_mean") or -1) >= -0.18,
        "mdd_ok": (cell.get("MDD") or -1) >= -0.20,
        "sample_ok": cell.get("status") == "OK",
        "risk_adj_positive": (cell.get("risk_adjusted_return") or -1) > 0,
    }
    ok = all(checks.values())
    return {"is_good_entry": ok, "checks": checks, "verdict": "GOOD_ENTRY_CANDIDATE" if ok else "NO_EDGE_PROVEN"}


def run_distribution_lab(
    *,
    root: Path,
    cfg: dict[str, Any] | None = None,
    max_symbols: int = 120,
) -> dict[str, Any]:
    t0 = time.time()
    cost_rate = round_trip_cost_buy_sell(cfg)
    # lambdas configurable research-only
    try:
        from ashare.config_loaders import load_yaml_config

        lc = load_yaml_config(cfg, "leader")
    except Exception:  # noqa: BLE001
        lc = {}
    dist_cfg = dict(lc.get("distribution") or {})
    lambda_ld = float(dist_cfg.get("lambda_ld", 0.35))
    lambda_dd = float(dist_cfg.get("lambda_dd", 0.50))

    rows = load_or_build_rows(root, cfg, max_symbols=max_symbols)
    cache = root / "data" / "cache" / "daily"
    enriched: list[dict[str, Any]] = []
    df_cache: dict[str, pd.DataFrame] = {}
    for r in rows:
        sym = r["symbol"]
        path = cache / f"{sym.replace('.', '_')}.parquet"
        if not path.exists():
            enriched.append(r)
            continue
        if sym not in df_cache:
            df_cache[sym] = pd.read_parquet(path)
        try:
            enriched.append(enrich_sample_from_bars(r, df_cache[sym], cost_rate=cost_rate))
        except Exception:  # noqa: BLE001
            enriched.append(r)
    enriched = tag_reaccel_paths(enriched)

    by_mode = {m: [r for r in enriched if r.get("entry_mode") == m] for m in FOCUS_MODES}

    mode_dist = {m: cell_summary(rs, cost_rate=cost_rate, lambda_ld=lambda_ld, lambda_dd=lambda_dd) for m, rs in by_mode.items()}

    # DIRECT_CHASE by board
    chase_by_board = {}
    for b in ("1", "2", "3", "4", "5", "6+"):
        subset = [r for r in by_mode["DIRECT_CHASE"] if r.get("board_bucket") == b]
        chase_by_board[b] = cell_summary(subset, cost_rate=cost_rate, lambda_ld=lambda_ld, lambda_dd=lambda_dd)

    # PULLBACK depth + health
    pb_depth = {}
    for bucket in ("0~-3%", "-3%~-7%", "-7%+"):
        subset = [r for r in by_mode["PULLBACK"] if r.get("pullback_depth_bucket") == bucket]
        pb_depth[bucket] = cell_summary(subset, cost_rate=cost_rate, lambda_ld=lambda_ld, lambda_dd=lambda_dd)
    pb_health = {}
    for h in ("HEALTHY_PULLBACK", "DANGEROUS_PULLBACK", "NEUTRAL_PULLBACK"):
        subset = [r for r in by_mode["PULLBACK"] if r.get("pullback_health") == h]
        pb_health[h] = cell_summary(subset, cost_rate=cost_rate, lambda_ld=lambda_ld, lambda_dd=lambda_dd)

    # REACCELERATION paths
    reaccel_paths = {}
    for p in ("AFTER_PULLBACK", "AFTER_DIVERGENCE", "AFTER_EXTREME", "DIRECT_REACCEL"):
        subset = [r for r in by_mode["REACCELERATION"] if r.get("reaccel_path") == p]
        reaccel_paths[p] = cell_summary(subset, cost_rate=cost_rate, lambda_ld=lambda_ld, lambda_dd=lambda_dd)
    repaired = [r for r in by_mode["REACCELERATION"] if r.get("structure_repaired")]
    reaccel_paths["STRUCTURE_REPAIRED"] = cell_summary(repaired, cost_rate=cost_rate, lambda_ld=lambda_ld, lambda_dd=lambda_dd)

    # Board × Entry matrix
    board_entry = {}
    best_cell = None
    for b in ("2", "3", "4", "5", "6+"):
        for m in ("DIRECT_CHASE", "PULLBACK", "REACCELERATION"):
            subset = [r for r in enriched if r.get("board_bucket") == b and r.get("entry_mode") == m]
            cell = cell_summary(subset, cost_rate=cost_rate, lambda_ld=lambda_ld, lambda_dd=lambda_dd)
            key = f"{b}|{m}"
            board_entry[key] = cell
            if cell.get("status") in {"OK", "LOW_SAMPLE"} and cell.get("risk_adjusted_return") is not None:
                if best_cell is None or cell["risk_adjusted_return"] > best_cell[1]:
                    best_cell = (key, cell["risk_adjusted_return"], cell)

    # Stage × Board × Entry (decision matrix)
    decision_matrix = {}
    for r in enriched:
        key = f"{r.get('stage')}|{r.get('board_bucket')}|{r.get('entry_mode')}"
        decision_matrix.setdefault(key, []).append(r)
    decision_summary = {
        k: cell_summary(v, cost_rate=cost_rate, lambda_ld=lambda_ld, lambda_dd=lambda_dd)
        for k, v in sorted(decision_matrix.items(), key=lambda x: -len(x[1]))
    }

    # Good entry evaluation per mode
    good_gates = {m: good_entry_gate(mode_dist[m]) for m in FOCUS_MODES}

    # Compare DIRECT_CHASE vs PULLBACK headline
    chase = mode_dist["DIRECT_CHASE"]
    pull = mode_dist["PULLBACK"]

    # Why BUY_READY=0
    dry_path = root / "data" / "leader" / "dry_run_latest.json"
    dry = json.loads(dry_path.read_text(encoding="utf-8")) if dry_path.exists() else {}
    buy_ready_why = {
        "dataset_timing_BUY_READY": sum(1 for r in enriched if r.get("trade_timing_action") == "BUY_READY"),
        "dataset_timing_BUY_CANDIDATE": sum(1 for r in enriched if r.get("trade_timing_action") == "BUY_CANDIDATE"),
        "dataset_timing_WAIT": sum(1 for r in enriched if r.get("trade_timing_action") == "WAIT"),
        "dry_run_buy_ready_n": dry.get("buy_ready_n"),
        "reasons": [
            "多数样本处于 EXTREME/追涨，trade_timing 强制 WAIT",
            "BUY_READY 需 TREND/EARLY + board>=2 + timing>=0.72，阈值未降低",
            "reentry_score 未校准，不能作为放宽依据",
            "research_only=true，不改 canonical BUY",
        ],
    }

    any_good = any(g.get("is_good_entry") for g in good_gates.values())
    risk_adj_edge = bool(
        best_cell
        and best_cell[1] > 0
        and (board_entry.get(best_cell[0]) or {}).get("status") == "OK"
        and (board_entry.get(best_cell[0]) or {}).get("limit_down_rate", 1) <= 0.20
    )

    answers = {
        "1_chase_mean_from_few_winners": _answer_winner_concentration(chase)
        + f" 更关键：收盘到收盘均值={chase.get('mean_return')}，但 T+1开盘买入扣费后净期望="
        f"{((chase.get('ev_t1open_net') or {}).get('t+5') or {}).get('ev')}（由高开/滑点吞噬）。",
        "2_chase_high_ld_why": _answer_chase_ld(chase, chase_by_board),
        "3_pullback_low_ld_why": _answer_pullback_ld(pull, pb_health, pb_depth),
        "4_best_pullback_type": _answer_best_pullback(pb_health, pb_depth),
        "5_reaccel_no_edge_why": _answer_reaccel(mode_dist["REACCELERATION"], reaccel_paths),
        "6_best_board_entry": {
            "cell": best_cell[0] if best_cell else None,
            "risk_adjusted_return": best_cell[1] if best_cell else None,
            "n": (best_cell[2] or {}).get("n") if best_cell else None,
            "status": (best_cell[2] or {}).get("status") if best_cell else None,
            "limit_down_rate": (best_cell[2] or {}).get("limit_down_rate") if best_cell else None,
            "note": "按 risk_adjusted_return 排序；LOW_SAMPLE 仅作线索，不构成证明。",
        },
        "7_continue_reentry_score": "NO — mark REENTRY_SCORE_UNCALIBRATED; do not use for BUY",
        "8_risk_adjusted_entry_edge": "YES_CANDIDATE" if risk_adj_edge else "NO_EDGE_PROVEN",
        "9_ready_for_param_opt": False,
        "10_why_buy_ready_zero": buy_ready_why,
        "overall": "NO_EDGE_PROVEN" if not any_good else "PARTIAL_CANDIDATE_ONLY",
        "pullback_net_ev_positive": bool(
            (((pull.get("ev_t1open_net") or {}).get("t+5") or {}).get("ev") or -1) > 0
        ),
        "chase_net_ev_positive": bool(
            (((chase.get("ev_t1open_net") or {}).get("t+5") or {}).get("ev") or -1) > 0
        ),
    }
    # param opt readiness: need good gate + stable sample
    answers["9_ready_for_param_opt"] = bool(
        good_gates.get("PULLBACK", {}).get("is_good_entry") and (pull.get("n") or 0) >= 80
    )

    report = {
        "meta": {
            "n_samples": len(enriched),
            "elapsed_sec": round(time.time() - t0, 2),
            "llm_calls": 0,
            "tokens": 0,
            "cost_rate_round_trip": cost_rate,
            "lambda_ld": lambda_ld,
            "lambda_dd": lambda_dd,
            "params_frozen": True,
            "reentry_score_status": "REENTRY_SCORE_UNCALIBRATED",
            "entry_quality_note": "research-only; not wired to BUY pipeline",
        },
        "mode_distribution": mode_dist,
        "direct_chase_by_board": chase_by_board,
        "pullback_by_depth": pb_depth,
        "pullback_by_health": pb_health,
        "reacceleration_paths": reaccel_paths,
        "board_x_entry": board_entry,
        "decision_matrix": {k: v for k, v in list(decision_summary.items())[:80]},
        "good_entry_gates": good_gates,
        "chase_vs_pullback": {
            "DIRECT_CHASE": _headline(chase),
            "PULLBACK": _headline(pull),
        },
        "answers": answers,
        "buy_ready_why": buy_ready_why,
    }

    out_dir = root / "data" / "leader"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "entry_distribution_latest.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    # enriched preview samples for UI charts
    preview = []
    for m in FOCUS_MODES:
        for r in by_mode[m][:80]:
            preview.append(
                {
                    "entry_mode": r.get("entry_mode"),
                    "board_bucket": r.get("board_bucket"),
                    "stage": r.get("stage"),
                    "pullback_depth_bucket": r.get("pullback_depth_bucket"),
                    "pullback_health": r.get("pullback_health"),
                    "reaccel_path": r.get("reaccel_path"),
                    "entry_quality": r.get("entry_quality"),
                    "t+5": (r.get("labels") or {}).get("t+5"),
                    "t+5_net": (r.get("labels") or {}).get("t+5_net_t1open"),
                    "mae": (r.get("labels") or {}).get("mae"),
                    "mdd": (r.get("labels") or {}).get("max_drawdown"),
                    "ld5": (r.get("labels") or {}).get("t+5_limit_down"),
                }
            )
    (out_dir / "entry_distribution_preview.json").write_text(
        json.dumps(preview, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return report


def _headline(cell: dict[str, Any]) -> dict[str, Any]:
    t5 = ((cell.get("distribution") or {}).get("t+5")) or {}
    return {
        "n": cell.get("n"),
        "status": cell.get("status"),
        "mean": cell.get("mean_return"),
        "median": cell.get("median_return"),
        "win_rate": cell.get("win_rate"),
        "limit_down_rate": cell.get("limit_down_rate"),
        "MDD": cell.get("MDD"),
        "MAE_mean": cell.get("MAE_mean"),
        "risk_adjusted_return": cell.get("risk_adjusted_return"),
        "p10": t5.get("p10"),
        "p90": t5.get("p90"),
        "worst": t5.get("worst"),
        "best": t5.get("best"),
        "top10pct_share_of_positive_pnl": t5.get("top10pct_share_of_positive_pnl"),
        "histogram": t5.get("histogram"),
        "ev_net_t5": ((cell.get("ev_t1open_net") or {}).get("t+5") or {}).get("ev"),
        "net_mean_t5": ((cell.get("ev_t1open_net") or {}).get("t+5") or {}).get("net_mean"),
    }


def _answer_winner_concentration(chase: dict[str, Any]) -> str:
    wc = chase.get("winner_concentration") or {}
    share = wc.get("top10pct_share_of_positive_pnl")
    gap = wc.get("mean_minus_median")
    if share is None:
        return "样本不足，无法判断均值是否由极端赢家驱动。"
    if share >= 0.45 or (gap is not None and gap > 0.03):
        return (
            f"是偏极端驱动：头部约10%样本贡献正收益池的 {share:.0%}；"
            f"均值-中位数差={gap}."
        )
    return f"不完全是少数赢家：头部10%约占正收益池 {share:.0%}；均值-中位数差={gap}."


def _answer_chase_ld(chase: dict[str, Any], by_board: dict[str, Any]) -> str:
    parts = [f"整体五日跌停率={chase.get('limit_down_rate')}。"]
    for b, cell in by_board.items():
        if cell.get("n", 0) >= MIN_SAMPLE_SOFT:
            parts.append(f"{b}板 LD={cell.get('limit_down_rate')} mean={cell.get('mean_return')}")
    parts.append("高连板追涨处于拥挤定价，次日分歧/炸板/补跌概率高。")
    return " ".join(parts)


def _answer_pullback_ld(pull: dict[str, Any], health: dict[str, Any], depth: dict[str, Any]) -> str:
    return (
        f"回踩整体 LD={pull.get('limit_down_rate')}（显著低于追涨）。"
        f"健康回踩 LD={(health.get('HEALTHY_PULLBACK') or {}).get('limit_down_rate')}；"
        f"危险回踩 LD={(health.get('DANGEROUS_PULLBACK') or {}).get('limit_down_rate')}。"
        "风险已部分释放、缩量结构更常见，故跌停率更低。"
    )


def _answer_best_pullback(health: dict[str, Any], depth: dict[str, Any]) -> dict[str, Any]:
    cands = []
    for name, cell in {**{f"health:{k}": v for k, v in health.items()}, **{f"depth:{k}": v for k, v in depth.items()}}.items():
        if cell.get("status") in {"OK", "LOW_SAMPLE"} and cell.get("risk_adjusted_return") is not None:
            cands.append((name, cell["risk_adjusted_return"], cell))
    cands.sort(key=lambda x: x[1], reverse=True)
    if not cands:
        return {"best": None, "note": "INSUFFICIENT_SAMPLE"}
    top = cands[0]
    return {
        "best": top[0],
        "risk_adjusted_return": top[1],
        "n": top[2].get("n"),
        "status": top[2].get("status"),
        "mean": top[2].get("mean_return"),
        "ld": top[2].get("limit_down_rate"),
        "note": "Research ranking only; LOW_SAMPLE cells are not proven.",
    }


def _answer_reaccel(cell: dict[str, Any], paths: dict[str, Any]) -> str:
    bits = [
        f"再加速整体 T+5 mean={cell.get('mean_return')} LD={cell.get('limit_down_rate')}。",
    ]
    for k, v in paths.items():
        if v.get("n", 0) >= MIN_SAMPLE_SOFT:
            bits.append(f"{k}: n={v.get('n')} mean={v.get('mean_return')} LD={v.get('limit_down_rate')} rar={v.get('risk_adjusted_return')}")
    bits.append("当前定义偏松，可能混入未完成风险释放的假突破。")
    return " ".join(bits)


def render_distribution_report(report: dict[str, Any]) -> str:
    meta = report.get("meta") or {}
    ans = report.get("answers") or {}
    lines = [
        "# ENTRY DISTRIBUTION REPORT",
        "",
        f"- samples: **{meta.get('n_samples')}**",
        f"- elapsed: {meta.get('elapsed_sec')}s | LLM: {meta.get('llm_calls')} | Token: {meta.get('tokens')}",
        f"- round-trip cost rate: {meta.get('cost_rate_round_trip')}",
        f"- reentry_score: **{meta.get('reentry_score_status')}**",
        f"- overall: **{ans.get('overall')}**",
        "",
        "## Mode distribution (T+5 focus)",
        "",
    ]
    for m, cell in (report.get("mode_distribution") or {}).items():
        t5 = ((cell.get("distribution") or {}).get("t+5")) or {}
        lines.append(
            f"### {m} (n={cell.get('n')}, {cell.get('status')})\n"
            f"- mean={t5.get('mean')} median={t5.get('median')} std={t5.get('std')}\n"
            f"- p10={t5.get('p10')} p25={t5.get('p25')} p75={t5.get('p75')} p90={t5.get('p90')}\n"
            f"- best={t5.get('best')} worst={t5.get('worst')}\n"
            f"- win={t5.get('positive_return_rate')} LD={cell.get('limit_down_rate')} MDD={cell.get('MDD')} MAE={cell.get('MAE_mean')}\n"
            f"- gt5={t5.get('return_gt_5')} gt10={t5.get('return_gt_10')} lt-10={t5.get('return_lt_-10')}\n"
            f"- top10% of +PnL share={t5.get('top10pct_share_of_positive_pnl')}\n"
            f"- EV net T+1open={((cell.get('ev_t1open_net') or {}).get('t+5') or {}).get('ev')} "
            f"net_mean={((cell.get('ev_t1open_net') or {}).get('t+5') or {}).get('net_mean')}\n"
            f"- risk_adjusted_return={cell.get('risk_adjusted_return')}\n"
        )
    lines += ["## DIRECT_CHASE by board", ""]
    for b, cell in (report.get("direct_chase_by_board") or {}).items():
        lines.append(
            f"- {b}板: n={cell.get('n')} status={cell.get('status')} "
            f"mean={cell.get('mean_return')} med={cell.get('median_return')} "
            f"win={cell.get('win_rate')} LD={cell.get('limit_down_rate')} rar={cell.get('risk_adjusted_return')}"
        )
    lines += ["", "## PULLBACK depth / health", ""]
    for k, cell in (report.get("pullback_by_depth") or {}).items():
        lines.append(f"- depth {k}: n={cell.get('n')} mean={cell.get('mean_return')} LD={cell.get('limit_down_rate')} rar={cell.get('risk_adjusted_return')}")
    for k, cell in (report.get("pullback_by_health") or {}).items():
        lines.append(f"- {k}: n={cell.get('n')} mean={cell.get('mean_return')} LD={cell.get('limit_down_rate')} MDD={cell.get('MDD')} rar={cell.get('risk_adjusted_return')}")
    lines += ["", "## REACCELERATION paths", ""]
    for k, cell in (report.get("reacceleration_paths") or {}).items():
        lines.append(f"- {k}: n={cell.get('n')} mean={cell.get('mean_return')} LD={cell.get('limit_down_rate')} rar={cell.get('risk_adjusted_return')}")
    lines += ["", "## Good-entry gates", ""]
    for m, g in (report.get("good_entry_gates") or {}).items():
        lines.append(f"- {m}: {g.get('verdict')} checks={g.get('checks')}")
    lines += ["", "## Answers", ""]
    for k, v in ans.items():
        lines.append(f"- **{k}**: {v}")
    lines += ["", "## Notes", "", "- BUY thresholds unchanged.", "- No LLM / No ML.", "- entry_quality & risk_adjusted_entry_score are research-only.", ""]
    return "\n".join(lines)
