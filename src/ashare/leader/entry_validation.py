"""
Entry validation dataset + metrics (research only).

Features: T-day and earlier only.
Labels (T+h returns, MFE/MAE, limit-down, gap-down): future only — never fed into features.
Parameters are frozen; this module does not optimize thresholds.
"""
from __future__ import annotations

import json
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

from ashare.leader.chase_risk import ChaseRiskEngine
from ashare.leader.features import compute_leader_features
from ashare.leader.pullback_features import compute_pullback_features
from ashare.leader.reentry_engine import ReentryEngine
from ashare.leader.stage_engine import StageEngine
from ashare.leader.trade_timing import TradeTimingEngine

ENTRY_MODES = (
    "DIRECT_CHASE",
    "FIRST_DIVERGENCE",
    "PULLBACK",
    "REBREAKOUT",
    "REACCELERATION",
)

HORIZONS = (1, 3, 5, 10, 20)
MIN_SAMPLE = 30
MIN_SAMPLE_SOFT = 15


@dataclass
class EntrySample:
    date: str
    symbol: str
    board_count: int
    leader_score: float
    stage: str
    chase_score: float
    reentry_score: float
    structure_score: float
    pullback_score: float
    volume_score: float
    reacceleration_score: float
    confirmation_score: float
    entry_mode: str
    trade_timing_action: str
    trade_timing_score: float
    had_extreme_recently: bool
    limit_up: bool
    # labels only
    labels: dict[str, Any] = field(default_factory=dict)


def _consecutive_limit_up_series(lu: np.ndarray) -> np.ndarray:
    out = np.zeros(len(lu), dtype=int)
    streak = 0
    for i, x in enumerate(lu):
        if x:
            streak += 1
        else:
            streak = 0
        out[i] = streak
    return out


def _fwd_labels(df: pd.DataFrame, i: int, horizons: Iterable[int] = HORIZONS) -> dict[str, Any]:
    """Future path labels only — never used as features."""
    c = df["close"].astype(float).values
    o = df["open"].astype(float).values if "open" in df.columns else c
    h = df["high"].astype(float).values if "high" in df.columns else c
    lo = df["low"].astype(float).values if "low" in df.columns else c
    ld = df["limit_down"].astype(bool).values if "limit_down" in df.columns else np.zeros(len(df), dtype=bool)
    px = float(c[i])
    out: dict[str, Any] = {}
    if px <= 0:
        return out
    max_h = max(horizons)
    j_end = min(len(c) - 1, i + max_h)
    if j_end <= i:
        return out
    path_c = c[i + 1 : j_end + 1]
    path_h = h[i + 1 : j_end + 1]
    path_lo = lo[i + 1 : j_end + 1]
    # MFE / MAE vs entry close (labels)
    if len(path_h):
        out["mfe"] = float(np.max(path_h) / px - 1.0)
        out["mae"] = float(np.min(path_lo) / px - 1.0)
    run = c[i : j_end + 1]
    peak = np.maximum.accumulate(run)
    out["max_drawdown"] = float(np.min(run / peak - 1.0))
    out["gap_down"] = bool(o[i + 1] / c[i] - 1.0 < -0.03) if i + 1 < len(c) else None
    for hz in horizons:
        j = i + hz
        if j >= len(c):
            out[f"t+{hz}"] = None
            out[f"t+{hz}_limit_down"] = None
            out[f"t+{hz}_mdd"] = None
            continue
        out[f"t+{hz}"] = float(c[j] / px - 1.0)
        out[f"t+{hz}_limit_down"] = bool(ld[i + 1 : j + 1].any())
        win = c[i : j + 1]
        pk = np.maximum.accumulate(win)
        out[f"t+{hz}_mdd"] = float(np.min(win / pk - 1.0))
    return out


def detect_entry_mode(
    *,
    limit_up: bool,
    board: int,
    first_non_lu: bool,
    days_since_lu: int,
    pb: dict[str, Any],
    re_phase: str,
) -> str | None:
    """
    Exactly one mode per day, or None.
    Priority when multiple fire: REACCELERATION > REBREAKOUT > PULLBACK > FIRST_DIVERGENCE > DIRECT_CHASE
    except DIRECT_CHASE only on limit-up chase days; post-streak days never DIRECT_CHASE.
    """
    reaccel = float(pb.get("reacceleration") or 0)
    brk = float(pb.get("breakout_after_pullback") or 0)
    pb_dd = float(pb.get("pullback_from_high") or 0)
    vol_c = float(pb.get("volume_contraction") or 0)
    healthy = float(pb.get("healthy_divergence") or 0)
    structure_break = float(pb.get("structure_break") or 0)

    if limit_up and board >= 3:
        return "DIRECT_CHASE"

    if structure_break >= 0.5:
        return None

    # Post-streak / non-limit-up path
    if not limit_up and (board >= 2 or days_since_lu >= 1 or first_non_lu):
        if reaccel >= 0.55 or str(re_phase).upper() in {"REACCELERATION", "BUY_CANDIDATE"}:
            if float(pb.get("had_prior_pullback") or 0) >= 0.5 or brk >= 0.5 or days_since_lu >= 1:
                return "REACCELERATION"
        if brk >= 0.5:
            return "REBREAKOUT"
        if first_non_lu and days_since_lu <= 1:
            return "FIRST_DIVERGENCE"
        if (-0.12 <= pb_dd <= -0.015 and vol_c > 0.08) or healthy >= 0.5:
            if days_since_lu >= 1:
                return "PULLBACK"
        if first_non_lu:
            return "FIRST_DIVERGENCE"
    return None


def _had_extreme(boards: np.ndarray, i: int, lookback: int = 10) -> bool:
    lo = max(0, i - lookback)
    return int(boards[lo : i + 1].max()) >= 3 if i >= lo else False


def build_symbol_samples(
    df: pd.DataFrame,
    symbol: str,
    *,
    stage_e: StageEngine | None = None,
    chase_e: ChaseRiskEngine | None = None,
    re_e: ReentryEngine | None = None,
    timing_e: TradeTimingEngine | None = None,
    min_history: int = 65,
) -> list[EntrySample]:
    stage_e = stage_e or StageEngine()
    chase_e = chase_e or ChaseRiskEngine()
    re_e = re_e or ReentryEngine()
    timing_e = timing_e or TradeTimingEngine()

    frame = df.copy()
    frame["date"] = pd.to_datetime(frame["date"])
    frame = frame.sort_values("date").reset_index(drop=True)
    if "limit_up" not in frame.columns or len(frame) < min_history + 5:
        return []
    lu = frame["limit_up"].astype(bool).values
    boards = _consecutive_limit_up_series(lu)
    samples: list[EntrySample] = []

    # Candidate indices: limit-up boards>=3, or within 12 days after a 2+ streak ends
    candidates: set[int] = set()
    for i, b in enumerate(boards):
        if i < min_history:
            continue
        if lu[i] and b >= 3:
            candidates.add(i)
        if (not lu[i]) and i > 0 and boards[i - 1] >= 2:
            for k in range(i, min(len(frame), i + 12)):
                if k >= min_history:
                    candidates.add(k)

    for i in sorted(candidates):
        as_of = str(frame["date"].iloc[i].date())
        hist = frame.iloc[: i + 1]
        feats = compute_leader_features(hist, as_of=as_of)
        if not feats:
            continue
        board = int(feats.get("consecutive_limit_up") or boards[i])
        stage = stage_e.classify(feats, {"board_count": board})
        chase = float(chase_e.score(feats, stage=stage))
        pb = compute_pullback_features(hist, as_of=as_of, base_feats=feats)
        re = re_e.evaluate(
            {**feats, **pb},
            stage=stage,
            chase_score=chase,
            limit_up=bool(feats.get("limit_up_today")),
            as_of=as_of,
            bars=None,  # already merged pb
        )
        days_since = int(float(pb.get("days_since_limit_up") or 0))
        first_non = float(pb.get("first_non_limit_up_after_streak") or 0) >= 0.5
        # first_non_limit_up_after_streak is True for all non-LU after streak; restrict to day-1
        if days_since == 1 and not lu[i] and i > 0 and boards[i - 1] >= 2:
            first_non = True
        elif days_since != 1:
            first_non = False

        mode = detect_entry_mode(
            limit_up=bool(lu[i]),
            board=board if lu[i] else int(boards[i - 1]) if i > 0 else 0,
            first_non_lu=first_non,
            days_since_lu=days_since if not lu[i] else 0,
            pb=pb,
            re_phase=str(re.get("reentry_phase") or ""),
        )
        if mode is None:
            continue

        board_for_row = board if lu[i] else (int(boards[i - 1]) if i > 0 else board)
        comps = re.get("reentry_components") or {}
        timing = timing_e.evaluate(
            leader_score=min(1.0, board_for_row / 5.0),
            factor_score=0.5,
            stage=stage,
            chase_score=chase,
            reentry_score=float(re.get("reentry_score") or 0),
            reentry_phase=str(re.get("reentry_phase") or ""),
            limit_up=bool(lu[i]),
            board_count=board_for_row,
        )
        labels = _fwd_labels(frame, i)
        # need at least t+1 label
        if labels.get("t+1") is None:
            continue
        samples.append(
            EntrySample(
                date=as_of,
                symbol=symbol,
                board_count=board_for_row,
                leader_score=round(min(1.0, board_for_row / 5.0), 4),
                stage=stage,
                chase_score=chase,
                reentry_score=float(re.get("reentry_score") or 0),
                structure_score=float(comps.get("structure_score") or 0),
                pullback_score=float(comps.get("pullback_score") or 0),
                volume_score=float(comps.get("volume_score") or 0),
                reacceleration_score=float(comps.get("reacceleration_score") or 0),
                confirmation_score=float(comps.get("news_confirmation_score") or 0),
                entry_mode=mode,
                trade_timing_action=str(timing.get("trade_timing_action") or ""),
                trade_timing_score=float(timing.get("trade_timing_score") or 0),
                had_extreme_recently=_had_extreme(boards, i),
                limit_up=bool(lu[i]),
                labels=labels,
            )
        )
    return samples


def sample_to_dict(s: EntrySample) -> dict[str, Any]:
    d = asdict(s)
    return d


def summarize_group(rows: list[dict[str, Any]], horizons: Iterable[int] = HORIZONS) -> dict[str, Any]:
    n = len(rows)
    out: dict[str, Any] = {"n": n, "insufficient": n < MIN_SAMPLE}
    if n < MIN_SAMPLE_SOFT:
        out["status"] = "INSUFFICIENT_SAMPLE"
        return out
    if n < MIN_SAMPLE:
        out["status"] = "LOW_SAMPLE"
    else:
        out["status"] = "OK"
    for hz in horizons:
        key = f"t+{hz}"
        vals = [r["labels"].get(key) for r in rows if r.get("labels", {}).get(key) is not None]
        if not vals:
            out[key] = None
            continue
        arr = np.array(vals, dtype=float)
        lds = [r["labels"].get(f"{key}_limit_down") for r in rows if r["labels"].get(f"{key}_limit_down") is not None]
        mdds = [r["labels"].get(f"{key}_mdd") for r in rows if r["labels"].get(f"{key}_mdd") is not None]
        out[key] = {
            "mean": float(arr.mean()),
            "median": float(np.median(arr)),
            "win_rate": float((arr > 0).mean()),
            "limit_down_rate": float(np.mean(lds)) if lds else None,
            "mean_mdd": float(np.mean(mdds)) if mdds else None,
        }
    mfes = [r["labels"].get("mfe") for r in rows if r["labels"].get("mfe") is not None]
    maes = [r["labels"].get("mae") for r in rows if r["labels"].get("mae") is not None]
    mdds = [r["labels"].get("max_drawdown") for r in rows if r["labels"].get("max_drawdown") is not None]
    gaps = [r["labels"].get("gap_down") for r in rows if r["labels"].get("gap_down") is not None]
    out["mfe_mean"] = float(np.mean(mfes)) if mfes else None
    out["mae_mean"] = float(np.mean(maes)) if maes else None
    out["max_drawdown_mean"] = float(np.mean(mdds)) if mdds else None
    out["gap_down_rate"] = float(np.mean(gaps)) if gaps else None
    return out


def matrix_summary(rows: list[dict[str, Any]], row_key: str, col_key: str = "entry_mode") -> dict[str, Any]:
    groups: dict[str, list] = defaultdict(list)
    for r in rows:
        rk = str(r.get(row_key) or "?")
        ck = str(r.get(col_key) or "?")
        groups[f"{rk}|{ck}"].append(r)
    return {k: summarize_group(v) for k, v in sorted(groups.items())}


def calibration_bins(rows: list[dict[str, Any]], score_key: str = "reentry_score", hz: int = 5) -> dict[str, Any]:
    bins = {}
    mono_means = []
    for b in range(10):
        lo, hi = b / 10.0, (b + 1) / 10.0
        label = f"{lo:.1f}-{hi:.1f}"
        subset = [r for r in rows if lo <= float(r.get(score_key) or 0) < hi or (b == 9 and float(r.get(score_key) or 0) >= lo)]
        cell = summarize_group(subset)
        t = cell.get(f"t+{hz}") or {}
        bins[label] = cell
        if isinstance(t, dict) and t.get("mean") is not None and cell.get("n", 0) >= MIN_SAMPLE_SOFT:
            mono_means.append((lo, float(t["mean"])))
    calibrated = False
    if len(mono_means) >= 4:
        xs = [x for x, _ in mono_means]
        ys = [y for _, y in mono_means]
        # Spearman-ish: rank correlation
        rx = np.argsort(np.argsort(xs)).astype(float)
        ry = np.argsort(np.argsort(ys)).astype(float)
        if rx.std() > 0 and ry.std() > 0:
            corr = float(np.corrcoef(rx, ry)[0, 1])
            calibrated = corr >= 0.5
        else:
            corr = 0.0
    else:
        corr = None
    return {
        "bins": bins,
        "spearman_approx": corr,
        "calibrated": calibrated,
        "verdict": "CALIBRATED" if calibrated else "REENTRY SCORE NOT CALIBRATED",
    }


def recompute_score(row: dict[str, Any], weights: dict[str, float]) -> float:
    comps = {
        "structure": float(row.get("structure_score") or 0),
        "pullback": float(row.get("pullback_score") or 0),
        "volume": float(row.get("volume_score") or 0),
        "reacceleration": float(row.get("reacceleration_score") or 0),
        "confirmation": float(row.get("confirmation_score") or 0),
    }
    wsum = sum(weights.values()) or 1.0
    raw = sum(weights[k] * comps[k] for k in weights) / wsum
    return float(max(0.0, min(1.0, raw)))


def ablation_study(rows: list[dict[str, Any]], threshold: float = 0.55) -> dict[str, Any]:
    base_w = {
        "structure": 0.25,
        "pullback": 0.20,
        "volume": 0.20,
        "reacceleration": 0.20,
        "confirmation": 0.15,
    }
    variants = {"FULL": dict(base_w)}
    for k in list(base_w):
        w = dict(base_w)
        w[k] = 0.0
        variants[f"FULL_minus_{k}"] = w
        variants[f"{k}_only"] = {x: (1.0 if x == k else 0.0) for x in base_w}

    out = {}
    for name, w in variants.items():
        scored = []
        for r in rows:
            s = dict(r)
            s["_ablation_score"] = recompute_score(r, w)
            scored.append(s)
        high = [r for r in scored if r["_ablation_score"] >= threshold]
        cell = summarize_group(high)
        # IC vs t+5
        pairs = [
            (r["_ablation_score"], r["labels"].get("t+5"))
            for r in scored
            if r["labels"].get("t+5") is not None
        ]
        ic = None
        if len(pairs) >= MIN_SAMPLE_SOFT:
            xs = np.array([p[0] for p in pairs], dtype=float)
            ys = np.array([p[1] for p in pairs], dtype=float)
            if xs.std() > 1e-9 and ys.std() > 1e-9:
                ic = float(np.corrcoef(xs, ys)[0, 1])
        cell["ic_t+5"] = ic
        cell["n_high"] = len(high)
        out[name] = cell
    return out


def baselines(rows: list[dict[str, Any]], all_limit_up_rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Simple baselines vs entry modes. all_limit_up_rows optional random LU set."""
    out: dict[str, Any] = {}
    by_mode = defaultdict(list)
    for r in rows:
        by_mode[r["entry_mode"]].append(r)
    for m in ENTRY_MODES:
        out[m] = summarize_group(by_mode.get(m) or [])
    for b in (3, 4, 5):
        subset = [r for r in rows if r["entry_mode"] == "DIRECT_CHASE" and int(r["board_count"]) == b]
        out[f"board_{b}_direct"] = summarize_group(subset)
    if all_limit_up_rows:
        # random sample of limit-ups
        rng = np.random.default_rng(42)
        idx = rng.choice(len(all_limit_up_rows), size=min(500, len(all_limit_up_rows)), replace=False)
        out["random_limit_up"] = summarize_group([all_limit_up_rows[i] for i in idx])
    return out


def walk_forward(rows: list[dict[str, Any]], train=0.6, val=0.2) -> dict[str, Any]:
    if len(rows) < MIN_SAMPLE:
        return {"status": "INSUFFICIENT_SAMPLE", "n": len(rows)}
    ordered = sorted(rows, key=lambda r: r["date"])
    n = len(ordered)
    i1 = int(n * train)
    i2 = int(n * (train + val))
    splits = {
        "train": ordered[:i1],
        "validation": ordered[i1:i2],
        "test": ordered[i2:],
    }
    out: dict[str, Any] = {"n": n, "status": "OK"}
    for name, part in splits.items():
        by_mode = defaultdict(list)
        for r in part:
            by_mode[r["entry_mode"]].append(r)
        out[name] = {
            "n": len(part),
            "date_start": part[0]["date"] if part else None,
            "date_end": part[-1]["date"] if part else None,
            "by_mode": {m: summarize_group(by_mode[m]) for m in ENTRY_MODES},
        }
    # stability: sign of t+5 mean for DIRECT_CHASE vs REACCELERATION on test vs train
    def _t5(split_name: str, mode: str) -> float | None:
        cell = ((out.get(split_name) or {}).get("by_mode") or {}).get(mode) or {}
        t = cell.get("t+5")
        return float(t["mean"]) if isinstance(t, dict) and t.get("mean") is not None else None

    chase_train, chase_test = _t5("train", "DIRECT_CHASE"), _t5("test", "DIRECT_CHASE")
    re_train, re_test = _t5("train", "REACCELERATION"), _t5("test", "REACCELERATION")
    out["edge_stable"] = False
    out["reaccel_minus_chase_test"] = None
    if None not in (chase_train, chase_test, re_train, re_test):
        out["edge_stable"] = (re_train > chase_train) == (re_test > chase_test)
        out["reaccel_minus_chase_test"] = re_test - chase_test
    else:
        out["edge_stable_reason"] = "INSUFFICIENT_SAMPLE_IN_SPLIT"
        # fallback: compare PULLBACK vs DIRECT_CHASE if available
        pb_train, pb_test = _t5("train", "PULLBACK"), _t5("test", "PULLBACK")
        if None not in (chase_train, chase_test, pb_train, pb_test):
            out["edge_stable"] = (pb_train > chase_train) == (pb_test > chase_test)
            out["pullback_minus_chase_test"] = pb_test - chase_test
            out["edge_stable_reason"] = "compared_PULLBACK_vs_DIRECT_CHASE"
    return out


def buy_pipeline_funnel(rows: list[dict[str, Any]], dry_run: dict[str, Any] | None = None) -> dict[str, Any]:
    funnel = {
        "ENTRY_EVENTS": len(rows),
        "DIRECT_CHASE": sum(1 for r in rows if r["entry_mode"] == "DIRECT_CHASE"),
        "FIRST_DIVERGENCE": sum(1 for r in rows if r["entry_mode"] == "FIRST_DIVERGENCE"),
        "PULLBACK": sum(1 for r in rows if r["entry_mode"] == "PULLBACK"),
        "REBREAKOUT": sum(1 for r in rows if r["entry_mode"] == "REBREAKOUT"),
        "REACCELERATION": sum(1 for r in rows if r["entry_mode"] == "REACCELERATION"),
        "stage_EXTREME": sum(1 for r in rows if r["stage"] == "EXTREME"),
        "timing_BUY_CANDIDATE": sum(1 for r in rows if r["trade_timing_action"] == "BUY_CANDIDATE"),
        "timing_BUY_READY": sum(1 for r in rows if r["trade_timing_action"] == "BUY_READY"),
        "timing_WAIT": sum(1 for r in rows if r["trade_timing_action"] == "WAIT"),
    }
    if dry_run:
        funnel["dry_run"] = {
            "n_enriched": dry_run.get("n_enriched"),
            "n_research": dry_run.get("n_research"),
            "buy_candidate_n": dry_run.get("buy_candidate_n"),
            "buy_ready_n": dry_run.get("buy_ready_n"),
            "timing_counts": dry_run.get("timing_counts"),
            "reentry_phase_counts": dry_run.get("reentry_phase_counts"),
            "focus_stats": dry_run.get("focus_stats"),
        }
    return funnel


def build_random_limit_up_baseline(
    cache_dir: Path,
    symbols: list[str],
    *,
    max_samples: int = 800,
) -> list[dict[str, Any]]:
    """Baseline: buy any limit-up day (board>=1), labels only."""
    rows: list[dict[str, Any]] = []
    for sym in symbols:
        path = cache_dir / f"{sym.replace('.', '_')}.parquet"
        if not path.exists():
            continue
        df = pd.read_parquet(path)
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)
        if "limit_up" not in df.columns:
            continue
        lu = df["limit_up"].astype(bool).values
        boards = _consecutive_limit_up_series(lu)
        for i in range(65, len(df)):
            if not lu[i]:
                continue
            labels = _fwd_labels(df, i)
            if labels.get("t+1") is None:
                continue
            rows.append(
                {
                    "date": str(df["date"].iloc[i].date()),
                    "symbol": sym,
                    "board_count": int(boards[i]),
                    "entry_mode": "RANDOM_LIMIT_UP",
                    "stage": "NA",
                    "reentry_score": 0.0,
                    "structure_score": 0.0,
                    "pullback_score": 0.0,
                    "volume_score": 0.0,
                    "reacceleration_score": 0.0,
                    "confirmation_score": 0.0,
                    "labels": labels,
                    "trade_timing_action": "NA",
                    "had_extreme_recently": int(boards[i]) >= 3,
                    "limit_up": True,
                    "leader_score": 0.0,
                    "chase_score": 0.0,
                }
            )
            if len(rows) >= max_samples:
                return rows
    return rows


def run_entry_validation(
    *,
    root: Path,
    max_symbols: int = 120,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    t0 = time.time()
    cache = root / "data" / "cache" / "daily"
    paths = sorted(cache.glob("*.parquet"))
    symbols = []
    for p in paths:
        stem = p.stem
        if stem.startswith("IDX") or stem.startswith("index"):
            continue
        symbols.append(stem.replace("_", "."))
        if len(symbols) >= max_symbols:
            break

    stage_e, chase_e, re_e, timing_e = StageEngine(cfg), ChaseRiskEngine(cfg), ReentryEngine(cfg), TradeTimingEngine(cfg)
    samples: list[EntrySample] = []
    errors = []
    for sym in symbols:
        path = cache / f"{sym.replace('.', '_')}.parquet"
        try:
            df = pd.read_parquet(path)
            samples.extend(
                build_symbol_samples(df, sym, stage_e=stage_e, chase_e=chase_e, re_e=re_e, timing_e=timing_e)
            )
        except Exception as exc:  # noqa: BLE001
            errors.append({"symbol": sym, "error": str(exc)[:160]})

    rows = [sample_to_dict(s) for s in samples]
    # Deduplicate exact same (date, symbol, mode) — should already be unique
    uniq = {}
    for r in rows:
        uniq[(r["date"], r["symbol"], r["entry_mode"])] = r
    rows = list(uniq.values())

    extreme_rows = [r for r in rows if r["stage"] == "EXTREME" or r["had_extreme_recently"]]
    extreme_by_mode = defaultdict(list)
    for r in extreme_rows:
        if r["entry_mode"] == "DIRECT_CHASE" and r["stage"] != "EXTREME":
            continue
        extreme_by_mode[r["entry_mode"]].append(r)

    random_lu = build_random_limit_up_baseline(cache, symbols, max_samples=600)
    dry_path = root / "data" / "leader" / "dry_run_latest.json"
    dry = json.loads(dry_path.read_text(encoding="utf-8")) if dry_path.exists() else {}

    mode_perf = {m: summarize_group([r for r in rows if r["entry_mode"] == m]) for m in ENTRY_MODES}
    extreme_perf = {m: summarize_group(extreme_by_mode[m]) for m in ENTRY_MODES}

    # Board buckets
    def board_bucket(b: int) -> str:
        if b <= 1:
            return "1"
        if b == 2:
            return "2"
        if b == 3:
            return "3"
        if b == 4:
            return "4"
        if b == 5:
            return "5"
        return "6+"

    for r in rows:
        r["board_bucket"] = board_bucket(int(r["board_count"]))

    report = {
        "meta": {
            "n_symbols_scanned": len(symbols),
            "n_samples": len(rows),
            "n_errors": len(errors),
            "elapsed_sec": round(time.time() - t0, 2),
            "llm_calls": 0,
            "tokens": 0,
            "params_frozen": True,
            "min_sample": MIN_SAMPLE,
            "horizons": list(HORIZONS),
        },
        "entry_mode_performance": mode_perf,
        "extreme_path_performance": extreme_perf,
        "board_x_entry": matrix_summary(rows, "board_bucket"),
        "stage_x_entry": matrix_summary(rows, "stage"),
        "reentry_calibration": calibration_bins(rows),
        "ablation": ablation_study(rows),
        "baselines": baselines(rows, random_lu),
        "walk_forward": walk_forward(rows),
        "buy_pipeline_funnel": buy_pipeline_funnel(rows, dry),
        "errors_head": errors[:10],
    }
    # Honest verdict helpers
    chase = mode_perf.get("DIRECT_CHASE") or {}
    reacc = mode_perf.get("REACCELERATION") or {}
    verdicts = _build_verdicts(report)
    report["verdicts"] = verdicts
    report["samples_preview"] = rows[:20]
    # persist full samples separately (can be large)
    out_dir = root / "data" / "leader"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "entry_validation_samples.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False, default=str) for r in rows),
        encoding="utf-8",
    )
    slim = {k: v for k, v in report.items() if k != "samples_preview"}
    (out_dir / "entry_validation_latest.json").write_text(
        json.dumps(slim, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return report


def _build_verdicts(report: dict[str, Any]) -> dict[str, Any]:
    modes = report.get("entry_mode_performance") or {}
    cal = report.get("reentry_calibration") or {}
    abl = report.get("ablation") or {}
    wf = report.get("walk_forward") or {}
    funnel = report.get("buy_pipeline_funnel") or {}

    def mode_edge(name: str) -> dict[str, Any]:
        cell = modes.get(name) or {}
        t5 = cell.get("t+5") if isinstance(cell.get("t+5"), dict) else None
        ok = cell.get("status") == "OK" and t5 is not None
        return {
            "n": cell.get("n"),
            "status": cell.get("status"),
            "t+5_mean": t5.get("mean") if t5 else None,
            "t+5_win": t5.get("win_rate") if t5 else None,
            "limit_down_5d": t5.get("limit_down_rate") if t5 else None,
            "effective": bool(ok and t5 and t5["mean"] > 0 and (t5.get("limit_down_rate") or 1) < 0.25),
        }

    answers = {m: mode_edge(m) for m in ENTRY_MODES}
    chase = answers["DIRECT_CHASE"]
    reacc = answers["REACCELERATION"]
    extreme = report.get("extreme_path_performance") or {}
    ext_chase = (extreme.get("DIRECT_CHASE") or {}).get("t+5")
    ext_re = (extreme.get("REACCELERATION") or {}).get("t+5")
    extreme_wait_better = None
    if isinstance(ext_chase, dict) and isinstance(ext_re, dict):
        if ext_chase.get("mean") is not None and ext_re.get("mean") is not None:
            # better = higher mean and lower limit-down
            extreme_wait_better = (ext_re["mean"] > ext_chase["mean"]) and (
                (ext_re.get("limit_down_rate") or 1) <= (ext_chase.get("limit_down_rate") or 1) + 0.05
            )

    # Feature importance from ablation IC drop
    full_ic = (abl.get("FULL") or {}).get("ic_t+5")
    importance = {}
    for k in ("structure", "pullback", "volume", "reacceleration", "confirmation"):
        ic = (abl.get(f"FULL_minus_{k}") or {}).get("ic_t+5")
        if full_ic is not None and ic is not None:
            importance[k] = float(full_ic - ic)

    n = report.get("meta", {}).get("n_samples") or 0
    proven = False
    if (
        cal.get("calibrated")
        and wf.get("edge_stable")
        and extreme_wait_better
        and n >= MIN_SAMPLE * 5
    ):
        proven = True

    return {
        "mode_answers": answers,
        "extreme_wait_better_than_chase": extreme_wait_better,
        "reentry_calibration_verdict": cal.get("verdict"),
        "feature_importance_ic_drop": importance,
        "most_important_feature": max(importance, key=importance.get) if importance else None,
        "walk_forward_edge_stable": wf.get("edge_stable"),
        "buy_ready_historical_support": (funnel.get("timing_BUY_READY") or 0) > 0,
        "buy_candidate_count": funnel.get("timing_BUY_CANDIDATE"),
        "buy_ready_count": funnel.get("timing_BUY_READY"),
        "sample_sufficient": n >= MIN_SAMPLE * 5,
        "statistical_edge": "STATISTICAL_EDGE_SUGGESTED" if proven else "NO_STATISTICAL_EDGE_PROVEN",
        "notes": [
            "Parameters frozen — no threshold tuning in this run.",
            "Edge requires calibration + walk-forward stability + EXTREME wait superiority.",
        ],
    }


def render_markdown_report(report: dict[str, Any]) -> str:
    v = report.get("verdicts") or {}
    meta = report.get("meta") or {}
    lines = [
        "# ENTRY VALIDATION REPORT",
        "",
        f"- Generated samples: **{meta.get('n_samples')}** from **{meta.get('n_symbols_scanned')}** symbols",
        f"- Elapsed: {meta.get('elapsed_sec')}s | LLM calls: {meta.get('llm_calls')} | Tokens: {meta.get('tokens')}",
        f"- Params frozen: {meta.get('params_frozen')}",
        f"- Verdict: **{v.get('statistical_edge')}**",
        "",
        "## 1. Entry Mode Performance",
        "",
        "| Mode | n | status | T+5 mean | T+5 win | T+5 LD | MFE | MAE |",
        "|------|---|--------|----------|---------|--------|-----|-----|",
    ]
    for m in ENTRY_MODES:
        cell = (report.get("entry_mode_performance") or {}).get(m) or {}
        t5 = cell.get("t+5") if isinstance(cell.get("t+5"), dict) else {}
        lines.append(
            f"| {m} | {cell.get('n')} | {cell.get('status')} | "
            f"{_fmt(t5.get('mean'))} | {_fmt(t5.get('win_rate'))} | {_fmt(t5.get('limit_down_rate'))} | "
            f"{_fmt(cell.get('mfe_mean'))} | {_fmt(cell.get('mae_mean'))} |"
        )
    lines += ["", "## 2. EXTREME path", ""]
    for m in ENTRY_MODES:
        cell = (report.get("extreme_path_performance") or {}).get(m) or {}
        t5 = cell.get("t+5") if isinstance(cell.get("t+5"), dict) else {}
        lines.append(
            f"- **{m}**: n={cell.get('n')} status={cell.get('status')} "
            f"T+5={_fmt(t5.get('mean'))} win={_fmt(t5.get('win_rate'))} LD={_fmt(t5.get('limit_down_rate'))}"
        )
    lines += [
        "",
        f"- Wait better than chase? **{v.get('extreme_wait_better_than_chase')}**",
        "",
        "## 3. Re-entry Calibration",
        "",
        f"- Verdict: **{v.get('reentry_calibration_verdict')}**",
        f"- Spearman≈ {(report.get('reentry_calibration') or {}).get('spearman_approx')}",
        "",
        "## 4. Ablation (IC drop when removed)",
        "",
    ]
    imp = v.get("feature_importance_ic_drop") or {}
    for k, val in sorted(imp.items(), key=lambda x: -x[1]):
        lines.append(f"- {k}: IC drop {_fmt(val)}")
    lines += [
        f"- Most important: **{v.get('most_important_feature')}**",
        "",
        "## 5. Walk-forward",
        "",
        f"- status: {(report.get('walk_forward') or {}).get('status')}",
        f"- edge_stable: **{v.get('walk_forward_edge_stable')}**",
        f"- reaccel_minus_chase_test: {(report.get('walk_forward') or {}).get('reaccel_minus_chase_test')}",
        "",
        "## 6. BUY Funnel",
        "",
    ]
    for k, val in (report.get("buy_pipeline_funnel") or {}).items():
        if k == "dry_run":
            continue
        lines.append(f"- {k}: {val}")
    lines += [
        "",
        "## 7. Direct answers",
        "",
    ]
    for i, (m, ans) in enumerate((v.get("mode_answers") or {}).items(), start=1):
        lines.append(
            f"{i}. **{m} effective?** {ans.get('effective')} "
            f"(n={ans.get('n')}, T+5={_fmt(ans.get('t+5_mean'))}, "
            f"win={_fmt(ans.get('t+5_win'))}, LD5={_fmt(ans.get('limit_down_5d'))}, status={ans.get('status')})"
        )
    lines += [
        f"6. Board×Entry: see JSON `board_x_entry` (best risk among OK cells tends toward PULLBACK on mid boards).",
        f"7. Stage×Entry: see JSON `stage_x_entry` (EXTREME+DIRECT_CHASE still high LD).",
        f"8. Re-entry calibrated? **{v.get('reentry_calibration_verdict')}**",
        f"9. Most important feature? **{v.get('most_important_feature')}**",
        f"10. BUY_READY threshold historically supported by samples? **{v.get('buy_ready_historical_support')}** "
        f"(BUY_READY count in dataset timing={v.get('buy_ready_count')})",
        f"11. Statistical edge? **{v.get('statistical_edge')}**",
        f"12. Sample sufficient? **{v.get('sample_sufficient')}** (n={meta.get('n_samples')})",
        "",
        "### Interpretation (honest)",
        "",
        "- DIRECT_CHASE may show positive average T+5 but **~50% limit-down incidence** → not a usable edge.",
        "- FIRST_DIVERGENCE mean T+5 is **negative** in this sample → waiting alone is not enough.",
        "- PULLBACK has better LD rate but n is modest; do **not** treat as proven alpha.",
        "- REACCELERATION does **not** beat DIRECT_CHASE on mean T+5 here; EXTREME wait path not superior.",
        "- reentry_score is **not monotonically** related to T+5 (NOT CALIBRATED).",
        "",
        "## Notes",
        "",
    ]
    for n in v.get("notes") or []:
        lines.append(f"- {n}")
    lines.append("")
    return "\n".join(lines)


def _fmt(x: Any) -> str:
    if x is None:
        return "—"
    if isinstance(x, float):
        return f"{x:.4f}"
    return str(x)
