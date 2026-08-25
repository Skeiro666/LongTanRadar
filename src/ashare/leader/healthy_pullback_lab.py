"""
Healthy Pullback Lab (research-only).

Goal: decide whether HEALTHY_PULLBACK can become a low-risk leader entry.
- No BUY threshold changes
- No LLM / No ML
- As-of features only; future returns are labels
- T+1 open fill + round-trip costs for net EV
"""
from __future__ import annotations

import json
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ashare.leader.chase_risk import ChaseRiskEngine
from ashare.leader.entry_distribution import (
    MIN_SAMPLE,
    MIN_SAMPLE_SOFT,
    cell_summary,
    classify_pullback_health,
    entry_quality_research,
    good_entry_gate,
    round_trip_cost_buy_sell,
    _board_bucket,
)
from ashare.leader.entry_validation import HORIZONS, _consecutive_limit_up_series, _fwd_labels
from ashare.leader.features import compute_leader_features
from ashare.leader.pullback_features import compute_pullback_features
from ashare.leader.reentry_engine import ReentryEngine
from ashare.leader.stage_engine import StageEngine


HEALTH_CONDITIONS = (
    "no_structure_break",
    "volume_contraction",
    "no_big_red",
    "no_high_open_low_close",
    "down_days_lt_3",
    "not_volume_dump",
)


def _pullback_depth_bucket_local(dd: float | None) -> str | None:
    if dd is None:
        return None
    x = float(dd)
    if x > -0.03:
        return "0~-3%"
    if x > -0.07:
        return "-3%~-7%"
    return "-7%+"


def health_flags(row: dict[str, Any]) -> dict[str, bool]:
    sb = float(row.get("structure_break") or 0)
    vc = float(row.get("volume_contraction") or 0)
    br = float(row.get("big_red_volume") or 0)
    holc = float(row.get("high_open_low_close") or 0)
    cd = float(row.get("consecutive_down_days") or 0)
    vr = float(row.get("volume_ratio_to_peak") or 0)
    dd = float(row.get("pullback_from_high") or 0)
    return {
        "no_structure_break": sb < 0.5,
        "volume_contraction": vc > 0.08,
        "no_big_red": br < 0.5,
        "no_high_open_low_close": holc < 0.5,
        "down_days_lt_3": cd < 3,
        "not_volume_dump": not (vr >= 0.85 and dd < -0.05),
    }


def is_healthy_with_ablation(flags: dict[str, bool], drop: str | None = None) -> bool:
    for k, ok in flags.items():
        if drop and k == drop:
            continue
        if not ok:
            return False
    return True


def is_pullback_day(pb: dict[str, Any], *, days_since_lu: int, limit_up: bool) -> bool:
    if limit_up:
        return False
    if days_since_lu < 1 or days_since_lu > 10:
        return False
    dd = float(pb.get("pullback_from_high") or 0)
    vc = float(pb.get("volume_contraction") or 0)
    healthy = float(pb.get("healthy_divergence") or 0)
    if float(pb.get("structure_break") or 0) >= 0.5:
        return False
    return (-0.15 <= dd <= -0.01 and vc >= 0.05) or healthy >= 0.5 or (-0.12 <= dd <= -0.02)


def scan_symbol_pullbacks(
    df: pd.DataFrame,
    symbol: str,
    *,
    cost_rate: float,
    stage_e: StageEngine,
    chase_e: ChaseRiskEngine,
    re_e: ReentryEngine,
    min_history: int = 65,
) -> list[dict[str, Any]]:
    frame = df.copy()
    frame["date"] = pd.to_datetime(frame["date"])
    frame = frame.sort_values("date").reset_index(drop=True)
    if "limit_up" not in frame.columns or len(frame) < min_history + 10:
        return []
    lu = frame["limit_up"].astype(bool).values
    boards = _consecutive_limit_up_series(lu)
    out: list[dict[str, Any]] = []

    for i in range(min_history, len(frame) - 1):
        if lu[i]:
            continue
        # require a recent 2+ board streak ending within 10 days
        look = boards[max(0, i - 10) : i]
        if len(look) == 0 or int(look.max()) < 2:
            continue
        # days since last limit-up
        last_lu = None
        for j in range(i - 1, max(-1, i - 15), -1):
            if lu[j]:
                last_lu = j
                break
        if last_lu is None:
            continue
        days_since = i - last_lu
        if days_since < 1 or days_since > 10:
            continue
        peak_board = int(boards[last_lu])

        as_of = str(frame["date"].iloc[i].date())
        hist = frame.iloc[: i + 1]
        feats = compute_leader_features(hist, as_of=as_of)
        if not feats:
            continue
        pb = compute_pullback_features(hist, as_of=as_of, base_feats=feats)
        if not is_pullback_day(pb, days_since_lu=days_since, limit_up=False):
            continue

        stage = stage_e.classify(feats, {"board_count": peak_board})
        chase = float(chase_e.score(feats, stage=stage))
        re = re_e.evaluate({**feats, **pb}, stage=stage, chase_score=chase, limit_up=False, as_of=as_of, bars=None)
        comps = re.get("reentry_components") or {}
        labels = _fwd_labels(frame, i)
        if labels.get("t+1") is None:
            continue
        # T+1 open net labels
        c = frame["close"].astype(float).values
        o = frame["open"].astype(float).values if "open" in frame.columns else c
        ld = frame["limit_down"].astype(bool).values if "limit_down" in frame.columns else np.zeros(len(frame), dtype=bool)
        entry = float(o[i + 1])
        if entry > 0:
            labels["entry_fill"] = "T+1_open"
            labels["entry_price"] = entry
            for h in HORIZONS:
                exit_i = i + h
                if exit_i >= len(c):
                    labels[f"t+{h}_gross_t1open"] = None
                    labels[f"t+{h}_net_t1open"] = None
                    continue
                gross = float(c[exit_i] / entry - 1.0)
                labels[f"t+{h}_gross_t1open"] = gross
                labels[f"t+{h}_net_t1open"] = float(gross - cost_rate)
                labels[f"t+{h}_limit_down_t1"] = bool(ld[i + 1 : exit_i + 1].any())

        row = {
            "date": as_of,
            "symbol": symbol,
            "board_count": peak_board,
            "board_bucket": _board_bucket(peak_board),
            "days_since_limit_up": days_since,
            "stage": stage,
            "chase_score": chase,
            "leader_score": min(1.0, peak_board / 5.0),
            "reentry_score": float(re.get("reentry_score") or 0),
            "reentry_phase": re.get("reentry_phase"),
            "structure_score": float(comps.get("structure_score") or 0),
            "pullback_score": float(comps.get("pullback_score") or 0),
            "volume_score": float(comps.get("volume_score") or 0),
            "reacceleration_score": float(comps.get("reacceleration_score") or 0),
            "confirmation_score": float(comps.get("news_confirmation_score") or 0),
            "pullback_from_high": pb.get("pullback_from_high"),
            "volume_contraction": pb.get("volume_contraction"),
            "volume_ratio_to_peak": pb.get("volume_ratio_to_peak"),
            "structure_break": pb.get("structure_break"),
            "big_red_volume": pb.get("big_red_volume"),
            "high_open_low_close": pb.get("high_open_low_close"),
            "consecutive_down_days": pb.get("consecutive_down_days"),
            "healthy_divergence": pb.get("healthy_divergence"),
            "breakout_after_pullback": pb.get("breakout_after_pullback"),
            "reacceleration": pb.get("reacceleration"),
            "had_prior_pullback": pb.get("had_prior_pullback"),
            "pullback_depth_bucket": _pullback_depth_bucket_local(pb.get("pullback_from_high")),
            "labels": labels,
            "entry_mode": "PULLBACK_SCAN",
            "reentry_score_status": "REENTRY_SCORE_UNCALIBRATED",
        }
        flags = health_flags(row)
        row["health_flags"] = flags
        row["pullback_health"] = classify_pullback_health(row)
        row["entry_quality"] = entry_quality_research(row)
        # next reacceleration within 5 trading days (label path only for research comparison)
        row["next_reaccel_offset"] = _find_reaccel_offset(frame, i, boards, lu, stage_e, chase_e, re_e)
        out.append(row)
    return out


def _find_reaccel_offset(
    frame: pd.DataFrame,
    i: int,
    boards: np.ndarray,
    lu: np.ndarray,
    stage_e: StageEngine,
    chase_e: ChaseRiskEngine,
    re_e: ReentryEngine,
    horizon: int = 5,
) -> int | None:
    """Lightweight as-of check: reacceleration / breakout flags only."""
    del stage_e, chase_e, re_e, boards  # unused — keep signature stable
    for k in range(1, horizon + 1):
        j = i + k
        if j >= len(frame) - 1 or lu[j]:
            continue
        as_of = str(frame["date"].iloc[j].date())
        hist = frame.iloc[: j + 1]
        pb = compute_pullback_features(hist, as_of=as_of)
        if float(pb.get("reacceleration") or 0) >= 0.55 or float(pb.get("breakout_after_pullback") or 0) >= 0.5:
            return k
    return None


def build_path_samples(rows: list[dict[str, Any]], cache: Path, cost_rate: float) -> dict[str, list[dict[str, Any]]]:
    """Construct buy-now vs wait-for-reaccel samples for healthy pullbacks."""
    buy_now = [r for r in rows if r.get("pullback_health") == "HEALTHY_PULLBACK"]
    wait_reaccel = []
    df_cache: dict[str, pd.DataFrame] = {}
    for r in buy_now:
        off = r.get("next_reaccel_offset")
        if off is None:
            continue
        sym = r["symbol"]
        path = cache / f"{sym.replace('.', '_')}.parquet"
        if not path.exists():
            continue
        if sym not in df_cache:
            df_cache[sym] = pd.read_parquet(path)
        df = df_cache[sym].copy()
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)
        dates = df["date"].dt.normalize()
        hits = np.where(dates == pd.Timestamp(r["date"]).normalize())[0]
        if not len(hits):
            continue
        i = int(hits[0]) + int(off)
        if i + 1 >= len(df):
            continue
        labels = _fwd_labels(df, i)
        c = df["close"].astype(float).values
        o = df["open"].astype(float).values if "open" in df.columns else c
        entry = float(o[i + 1])
        if entry <= 0 or labels.get("t+1") is None:
            continue
        for h in HORIZONS:
            exit_i = i + h
            if exit_i >= len(c):
                labels[f"t+{h}_gross_t1open"] = None
                labels[f"t+{h}_net_t1open"] = None
                continue
            gross = float(c[exit_i] / entry - 1.0)
            labels[f"t+{h}_gross_t1open"] = gross
            labels[f"t+{h}_net_t1open"] = float(gross - cost_rate)
        wait_reaccel.append(
            {
                **r,
                "date": str(df["date"].iloc[i].date()),
                "entry_mode": "HP_THEN_REACCEL",
                "labels": labels,
                "from_pullback_date": r["date"],
                "reaccel_offset": off,
            }
        )
    return {"HEALTHY_PULLBACK_NOW": buy_now, "HP_THEN_REACCEL": wait_reaccel}


def walk_forward_simple(rows: list[dict[str, Any]], cost_rate: float) -> dict[str, Any]:
    if len(rows) < MIN_SAMPLE:
        return {"status": "INSUFFICIENT_SAMPLE", "n": len(rows)}
    ordered = sorted(rows, key=lambda r: r["date"])
    n = len(ordered)
    i1, i2 = int(n * 0.6), int(n * 0.8)
    splits = {"train": ordered[:i1], "validation": ordered[i1:i2], "test": ordered[i2:]}
    out: dict[str, Any] = {"status": "OK", "n": n}
    nets = {}
    for name, part in splits.items():
        cell = cell_summary(part, cost_rate=cost_rate)
        out[name] = {
            "n": len(part),
            "date_start": part[0]["date"] if part else None,
            "date_end": part[-1]["date"] if part else None,
            "mean": cell.get("mean_return"),
            "ld": cell.get("limit_down_rate"),
            "rar": cell.get("risk_adjusted_return"),
            "net_ev": ((cell.get("ev_t1open_net") or {}).get("t+5") or {}).get("ev"),
            "status": cell.get("status"),
        }
        nets[name] = out[name]["net_ev"]
    # stability: train and test same sign of net EV
    if nets.get("train") is not None and nets.get("test") is not None:
        out["net_ev_sign_stable"] = (nets["train"] > 0) == (nets["test"] > 0)
        out["test_minus_train_net"] = nets["test"] - nets["train"]
    else:
        out["net_ev_sign_stable"] = False
    return out


def run_healthy_pullback_lab(
    *,
    root: Path,
    cfg: dict[str, Any] | None = None,
    max_symbols: int = 250,
) -> dict[str, Any]:
    t0 = time.time()
    cost_rate = round_trip_cost_buy_sell(cfg)
    try:
        from ashare.config_loaders import load_yaml_config

        lc = load_yaml_config(cfg, "leader")
    except Exception:  # noqa: BLE001
        lc = {}
    dist_cfg = dict(lc.get("distribution") or {})
    lambda_ld = float(dist_cfg.get("lambda_ld", 0.35))
    lambda_dd = float(dist_cfg.get("lambda_dd", 0.50))

    cache = root / "data" / "cache" / "daily"
    symbols = []
    for p in sorted(cache.glob("*.parquet")):
        if p.stem.startswith("IDX"):
            continue
        symbols.append(p.stem.replace("_", "."))
        if len(symbols) >= max_symbols:
            break

    stage_e, chase_e, re_e = StageEngine(cfg), ChaseRiskEngine(cfg), ReentryEngine(cfg)
    rows: list[dict[str, Any]] = []
    errors = []
    for sym in symbols:
        path = cache / f"{sym.replace('.', '_')}.parquet"
        try:
            df = pd.read_parquet(path)
            rows.extend(
                scan_symbol_pullbacks(df, sym, cost_rate=cost_rate, stage_e=stage_e, chase_e=chase_e, re_e=re_e)
            )
        except Exception as exc:  # noqa: BLE001
            errors.append({"symbol": sym, "error": str(exc)[:120]})

    # dedupe date+symbol
    uniq = {(r["date"], r["symbol"]): r for r in rows}
    rows = list(uniq.values())

    all_cell = cell_summary(rows, cost_rate=cost_rate, lambda_ld=lambda_ld, lambda_dd=lambda_dd)
    by_health = {
        h: cell_summary([r for r in rows if r.get("pullback_health") == h], cost_rate=cost_rate, lambda_ld=lambda_ld, lambda_dd=lambda_dd)
        for h in ("HEALTHY_PULLBACK", "DANGEROUS_PULLBACK", "NEUTRAL_PULLBACK")
    }
    by_depth = {
        d: cell_summary([r for r in rows if r.get("pullback_depth_bucket") == d], cost_rate=cost_rate, lambda_ld=lambda_ld, lambda_dd=lambda_dd)
        for d in ("0~-3%", "-3%~-7%", "-7%+")
    }
    by_board = {
        b: cell_summary(
            [r for r in rows if r.get("pullback_health") == "HEALTHY_PULLBACK" and r.get("board_bucket") == b],
            cost_rate=cost_rate,
            lambda_ld=lambda_ld,
            lambda_dd=lambda_dd,
        )
        for b in ("2", "3", "4", "5", "6+")
    }

    # condition ablation on healthy definition
    ablation = {}
    base_flags_rows = [(r, health_flags(r)) for r in rows]
    full_healthy = [r for r, f in base_flags_rows if is_healthy_with_ablation(f)]
    ablation["FULL_HEALTHY"] = cell_summary(full_healthy, cost_rate=cost_rate, lambda_ld=lambda_ld, lambda_dd=lambda_dd)
    for cond in HEALTH_CONDITIONS:
        subset = [r for r, f in base_flags_rows if is_healthy_with_ablation(f, drop=cond)]
        ablation[f"drop_{cond}"] = cell_summary(subset, cost_rate=cost_rate, lambda_ld=lambda_ld, lambda_dd=lambda_dd)
        # condition-only: only that condition true among pullback scans (weak)
        only = [r for r, f in base_flags_rows if f.get(cond)]
        ablation[f"require_{cond}"] = cell_summary(only, cost_rate=cost_rate, lambda_ld=lambda_ld, lambda_dd=lambda_dd)

    paths = build_path_samples(rows, cache, cost_rate)
    path_perf = {k: cell_summary(v, cost_rate=cost_rate, lambda_ld=lambda_ld, lambda_dd=lambda_dd) for k, v in paths.items()}

    hp_rows = [r for r in rows if r.get("pullback_health") == "HEALTHY_PULLBACK"]
    wf = walk_forward_simple(hp_rows, cost_rate)
    gate = good_entry_gate(by_health["HEALTHY_PULLBACK"])

    # stricter gate including net EV and walk-forward
    hp = by_health["HEALTHY_PULLBACK"]
    net_ev = ((hp.get("ev_t1open_net") or {}).get("t+5") or {}).get("ev")
    strict = {
        "positive_net_ev": bool(net_ev is not None and net_ev > 0),
        "ld_ok": (hp.get("limit_down_rate") or 1) <= 0.20,
        "sample_ok": hp.get("status") == "OK",
        "wf_sign_stable": bool(wf.get("net_ev_sign_stable")),
        "rar_nonneg": (hp.get("risk_adjusted_return") or -1) >= 0,
        "good_entry_gate": bool(gate.get("is_good_entry")),
    }
    proven = all(strict.values())

    # which ablation condition hurts most when dropped (net EV drop)
    importance = {}
    full_net = ((ablation["FULL_HEALTHY"].get("ev_t1open_net") or {}).get("t+5") or {}).get("ev")
    for cond in HEALTH_CONDITIONS:
        cell = ablation.get(f"drop_{cond}") or {}
        net = ((cell.get("ev_t1open_net") or {}).get("t+5") or {}).get("ev")
        if full_net is not None and net is not None:
            importance[cond] = float(full_net - net)

    answers = {
        "1_healthy_pullback_net_ev": net_ev,
        "2_healthy_vs_dangerous": {
            "healthy": _brief(by_health["HEALTHY_PULLBACK"]),
            "dangerous": _brief(by_health["DANGEROUS_PULLBACK"]),
        },
        "3_best_depth": _best_cell(by_depth),
        "4_best_board_for_hp": _best_cell(by_board),
        "5_buy_now_vs_wait_reaccel": {
            "buy_now": _brief(path_perf.get("HEALTHY_PULLBACK_NOW") or {}),
            "wait_reaccel": _brief(path_perf.get("HP_THEN_REACCEL") or {}),
            "prefer": _prefer_path(path_perf),
        },
        "6_most_important_health_condition": max(importance, key=importance.get) if importance else None,
        "7_condition_importance": importance,
        "8_walk_forward": wf,
        "9_ready_for_buy_candidate_research": bool(
            strict["positive_net_ev"] and strict["ld_ok"] and strict["sample_ok"] and (hp.get("n") or 0) >= 50
        ),
        "10_statistical_edge": "HEALTHY_PULLBACK_EDGE_SUGGESTED" if proven else "NO_EDGE_PROVEN",
        "strict_checks": strict,
        "note": "Not wired to BUY pipeline. BUY thresholds unchanged.",
    }

    report = {
        "meta": {
            "n_symbols": len(symbols),
            "n_pullback_scans": len(rows),
            "n_healthy": len(hp_rows),
            "elapsed_sec": round(time.time() - t0, 2),
            "llm_calls": 0,
            "tokens": 0,
            "cost_rate_round_trip": cost_rate,
            "params_frozen": True,
            "buy_pipeline_unchanged": True,
        },
        "all_pullback_scans": all_cell,
        "by_health": by_health,
        "by_depth": by_depth,
        "healthy_by_board": by_board,
        "condition_ablation": ablation,
        "path_performance": path_perf,
        "walk_forward": wf,
        "good_entry_gate": gate,
        "answers": answers,
        "errors_head": errors[:10],
    }

    out_dir = root / "data" / "leader"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "healthy_pullback_latest.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    preview = [
        {
            "date": r["date"],
            "symbol": r["symbol"],
            "board_bucket": r.get("board_bucket"),
            "pullback_health": r.get("pullback_health"),
            "pullback_depth_bucket": r.get("pullback_depth_bucket"),
            "t+5": (r.get("labels") or {}).get("t+5"),
            "t+5_net": (r.get("labels") or {}).get("t+5_net_t1open"),
            "ld5": (r.get("labels") or {}).get("t+5_limit_down"),
            "entry_quality": r.get("entry_quality"),
        }
        for r in hp_rows[:120]
    ]
    (out_dir / "healthy_pullback_preview.json").write_text(
        json.dumps(preview, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return report


def _brief(cell: dict[str, Any]) -> dict[str, Any]:
    return {
        "n": cell.get("n"),
        "status": cell.get("status"),
        "mean": cell.get("mean_return"),
        "median": cell.get("median_return"),
        "win": cell.get("win_rate"),
        "ld": cell.get("limit_down_rate"),
        "mdd": cell.get("MDD"),
        "mae": cell.get("MAE_mean"),
        "rar": cell.get("risk_adjusted_return"),
        "net_ev": ((cell.get("ev_t1open_net") or {}).get("t+5") or {}).get("ev"),
        "net_mean": ((cell.get("ev_t1open_net") or {}).get("t+5") or {}).get("net_mean"),
    }


def _best_cell(mapping: dict[str, dict[str, Any]]) -> dict[str, Any]:
    cands = []
    for k, cell in mapping.items():
        if cell.get("status") in {"OK", "LOW_SAMPLE"} and cell.get("risk_adjusted_return") is not None:
            cands.append((k, cell["risk_adjusted_return"], cell))
    if not cands:
        return {"best": None, "note": "INSUFFICIENT_SAMPLE"}
    cands.sort(key=lambda x: x[1], reverse=True)
    k, rar, cell = cands[0]
    return {"best": k, "rar": rar, **_brief(cell)}


def _prefer_path(path_perf: dict[str, dict[str, Any]]) -> str:
    a = path_perf.get("HEALTHY_PULLBACK_NOW") or {}
    b = path_perf.get("HP_THEN_REACCEL") or {}
    ra, rb = a.get("risk_adjusted_return"), b.get("risk_adjusted_return")
    na = ((a.get("ev_t1open_net") or {}).get("t+5") or {}).get("ev")
    nb = ((b.get("ev_t1open_net") or {}).get("t+5") or {}).get("ev")
    if ra is None and rb is None:
        return "INSUFFICIENT_SAMPLE"
    if rb is not None and (ra is None or rb > ra) and (nb is None or na is None or nb >= na):
        return "WAIT_FOR_REACCEL"
    if ra is not None and (rb is None or ra >= rb):
        return "BUY_ON_HEALTHY_PULLBACK"
    return "UNCLEAR"


def render_healthy_pullback_report(report: dict[str, Any]) -> str:
    meta = report.get("meta") or {}
    ans = report.get("answers") or {}
    lines = [
        "# HEALTHY PULLBACK LAB REPORT",
        "",
        f"- pullback scans: **{meta.get('n_pullback_scans')}** from **{meta.get('n_symbols')}** symbols",
        f"- healthy: **{meta.get('n_healthy')}**",
        f"- elapsed: {meta.get('elapsed_sec')}s | LLM: {meta.get('llm_calls')} | Token: {meta.get('tokens')}",
        f"- cost rate: {meta.get('cost_rate_round_trip')}",
        f"- verdict: **{ans.get('10_statistical_edge')}**",
        "",
        "## By health",
        "",
    ]
    for k, cell in (report.get("by_health") or {}).items():
        b = _brief(cell)
        lines.append(
            f"- **{k}**: n={b['n']} status={b['status']} mean={b['mean']} win={b['win']} "
            f"LD={b['ld']} net_ev={b['net_ev']} rar={b['rar']}"
        )
    lines += ["", "## Depth / Board", ""]
    for k, cell in (report.get("by_depth") or {}).items():
        b = _brief(cell)
        lines.append(f"- depth {k}: n={b['n']} mean={b['mean']} LD={b['ld']} net_ev={b['net_ev']} rar={b['rar']}")
    for k, cell in (report.get("healthy_by_board") or {}).items():
        b = _brief(cell)
        lines.append(f"- HP {k}板: n={b['n']} mean={b['mean']} LD={b['ld']} net_ev={b['net_ev']} rar={b['rar']}")
    lines += ["", "## Buy now vs wait reaccel", ""]
    pref = ans.get("5_buy_now_vs_wait_reaccel") or {}
    lines.append(f"- prefer: **{pref.get('prefer')}**")
    lines.append(f"- buy_now: {pref.get('buy_now')}")
    lines.append(f"- wait_reaccel: {pref.get('wait_reaccel')}")
    lines += ["", "## Condition importance (net EV drop when removed)", ""]
    for k, v in sorted((ans.get("7_condition_importance") or {}).items(), key=lambda x: -x[1]):
        lines.append(f"- {k}: {v}")
    lines += [
        "",
        "## Walk-forward",
        "",
        f"- {ans.get('8_walk_forward')}",
        "",
        "## Strict checks",
        "",
        f"- {ans.get('strict_checks')}",
        "",
        "## Answers",
        "",
        f"1. Healthy pullback net EV: {ans.get('1_healthy_pullback_net_ev')}",
        f"2. Healthy vs dangerous: {ans.get('2_healthy_vs_dangerous')}",
        f"3. Best depth: {ans.get('3_best_depth')}",
        f"4. Best board: {ans.get('4_best_board_for_hp')}",
        f"5. Path preference: {pref.get('prefer')}",
        f"6. Most important condition: {ans.get('6_most_important_health_condition')}",
        f"7. Ready for BUY_CANDIDATE research? {ans.get('9_ready_for_buy_candidate_research')}",
        f"8. Edge: **{ans.get('10_statistical_edge')}**",
        "",
        "## Notes",
        "",
        "- BUY thresholds unchanged; not wired to BUY pipeline.",
        "- reentry_score remains UNCALIBRATED.",
        "- No LLM / No ML.",
        "",
    ]
    return "\n".join(lines)
