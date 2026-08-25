#!/usr/bin/env python3
"""Historical entry-mode research for limit-up leaders (as-of, no look-ahead)."""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ashare.config import load_config
from ashare.leader.chase_risk import ChaseRiskEngine
from ashare.leader.features import compute_leader_features
from ashare.leader.reentry_engine import ReentryEngine
from ashare.leader.stage_engine import StageEngine
from ashare.leader.trade_timing import TradeTimingEngine


FOCUS_FAIL = [
    ("002412.SZ", "汉森制药"),
    ("603958.SH", "哈森股份"),
    ("601700.SH", "风范股份"),
    ("603330.SH", "天洋新材"),
    ("601212.SH", "白银有色"),
    ("603626.SH", "科森科技"),
    ("000620.SZ", "盈新发展"),
    ("600227.SH", "赤天化"),
]


def _fwd_stats(df: pd.DataFrame, i: int, horizons: list[int]) -> dict:
    c = df["close"].astype(float).values
    ld = df["limit_down"].astype(bool).values if "limit_down" in df.columns else np.zeros(len(df), dtype=bool)
    o = df["open"].astype(float).values if "open" in df.columns else c
    out = {}
    px = float(c[i])
    if px <= 0:
        return out
    peak = px
    trough = px
    for h in horizons:
        j = i + h
        if j >= len(c):
            out[f"t+{h}"] = None
            out[f"t+{h}_limit_down"] = None
            continue
        ret = float(c[j] / px - 1.0)
        out[f"t+{h}"] = ret
        # path max drawdown from entry to j
        window = c[i : j + 1]
        run_peak = np.maximum.accumulate(window)
        dd = float(np.min(window / run_peak - 1.0))
        out[f"t+{h}_mdd"] = dd
        out[f"t+{h}_limit_down"] = bool(ld[i + 1 : j + 1].any()) if j > i else bool(ld[j])
        if j > i:
            out[f"t+{h}_gap_down"] = bool(o[i + 1] / c[i] - 1.0 < -0.03)
        peak = max(peak, float(np.max(window)))
        trough = min(trough, float(np.min(window)))
    out["max_drawdown"] = float(trough / peak - 1.0) if peak > 0 else None
    return out


def _entry_index(df: pd.DataFrame, mode: str) -> int | None:
    lu = df["limit_up"].astype(bool).values if "limit_up" in df.columns else None
    if lu is None:
        return None
    # consecutive boards ending at i
    idxs = [i for i, x in enumerate(lu) if x]
    if not idxs:
        return None
    if mode == "first_limit_up":
        return idxs[0]
    if mode.startswith("board_"):
        need = int(mode.split("_")[1])
        streak = 0
        for i, x in enumerate(lu):
            streak = streak + 1 if x else 0
            if streak == need:
                return i
        return None
    if mode == "extreme_chase":
        # first day with 3+ consecutive limit-ups
        streak = 0
        for i, x in enumerate(lu):
            streak = streak + 1 if x else 0
            if streak >= 3:
                return i
        return None
    if mode == "first_divergence":
        streak = 0
        for i, x in enumerate(lu):
            if x:
                streak += 1
            elif streak >= 2:
                return i  # first non-LU after streak
            else:
                streak = 0
        return None
    if mode in {"pullback", "rebreakout", "reacceleration"}:
        # use engines on each day after a 2+ board streak
        stage_e = StageEngine()
        chase_e = ChaseRiskEngine()
        re_e = ReentryEngine()
        for i in range(60, len(df)):
            as_of = str(pd.Timestamp(df["date"].iloc[i]).date())
            feats = compute_leader_features(df.iloc[: i + 1], as_of=as_of)
            if not feats:
                continue
            board = int(feats.get("consecutive_limit_up") or 0)
            if board < 2 and float(feats.get("limit_up_count_5d") or 0) < 2:
                continue
            st = stage_e.classify(feats, {"board_count": board})
            ch = chase_e.score(feats, stage=st)
            re = re_e.annotate_from_bars(
                feats, df.iloc[: i + 1], stage=st, chase_score=ch, limit_up=bool(feats.get("limit_up_today")), as_of=as_of
            )
            phase = re.get("reentry_phase")
            if mode == "pullback" and phase in {"PULLBACK_WATCH", "DIVERGENCE"}:
                return i
            if mode == "rebreakout" and float(re.get("reentry_flags", {}).get("breakout_after_pullback") or 0) >= 0.5:
                return i
            if mode == "reacceleration" and phase in {"REACCELERATION", "BUY_CANDIDATE"}:
                return i
        return None
    return None


def analyze_symbol(path: Path, horizons: list[int], modes: list[str]) -> dict:
    df = pd.read_parquet(path)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    rows = {}
    for mode in modes:
        i = _entry_index(df, mode)
        if i is None or i < 60:
            rows[mode] = {"available": False}
            continue
        as_of = str(df["date"].iloc[i].date())
        feats = compute_leader_features(df.iloc[: i + 1], as_of=as_of)
        stage = StageEngine().classify(feats, {"board_count": int(feats.get("consecutive_limit_up") or 0)})
        chase = ChaseRiskEngine().score(feats, stage=stage)
        re = ReentryEngine().annotate_from_bars(
            feats, df.iloc[: i + 1], stage=stage, chase_score=chase, limit_up=bool(feats.get("limit_up_today")), as_of=as_of
        )
        board = int(feats.get("consecutive_limit_up") or 0)
        timing = TradeTimingEngine().evaluate(
            leader_score=min(1.0, board / 5.0),
            factor_score=0.5,
            stage=stage,
            chase_score=chase,
            reentry_score=float(re.get("reentry_score") or 0),
            reentry_phase=str(re.get("reentry_phase") or ""),
            limit_up=bool(feats.get("limit_up_today")),
            board_count=board,
        )
        fwd = _fwd_stats(df, i, horizons)
        rows[mode] = {
            "available": True,
            "as_of": as_of,
            "board": int(feats.get("consecutive_limit_up") or 0),
            "stage": stage,
            "chase_score": chase,
            "reentry_score": re.get("reentry_score"),
            "reentry_phase": re.get("reentry_phase"),
            "trade_timing_action": timing.get("trade_timing_action"),
            "failure": {
                "limit_down_1d": fwd.get("t+1_limit_down"),
                "limit_down_3d": fwd.get("t+3_limit_down"),
                "limit_down_5d": fwd.get("t+5_limit_down"),
                "gap_down": fwd.get("t+1_gap_down"),
                "max_drawdown": fwd.get("max_drawdown"),
                "crash_after_extreme": stage == "EXTREME" and (fwd.get("t+5") or 0) < -0.1,
            },
            **fwd,
        }
    return rows


def aggregate(per_sym: dict[str, dict], modes: list[str], horizons: list[int]) -> dict:
    agg = {}
    for mode in modes:
        samples = [v[mode] for v in per_sym.values() if v.get(mode, {}).get("available")]
        cell = {"n": len(samples)}
        for h in horizons:
            key = f"t+{h}"
            vals = [s[key] for s in samples if s.get(key) is not None]
            if not vals:
                cell[key] = None
                cell[f"{key}_win"] = None
                continue
            arr = np.array(vals, dtype=float)
            cell[key] = {"mean": float(arr.mean()), "median": float(np.median(arr)), "win_rate": float((arr > 0).mean())}
            lds = [s.get(f"{key}_limit_down") for s in samples if s.get(f"{key}_limit_down") is not None]
            cell[f"{key}_limit_down_rate"] = float(np.mean(lds)) if lds else None
            mdds = [s.get(f"{key}_mdd") for s in samples if s.get(f"{key}_mdd") is not None]
            cell[f"{key}_mean_mdd"] = float(np.mean(mdds)) if mdds else None
        agg[mode] = cell
    return agg


def main() -> int:
    cfg = load_config()
    cfg["_root"] = str(ROOT)
    lc = __import__("ashare.config_loaders", fromlist=["load_yaml_config"]).load_yaml_config(cfg, "leader")
    horizons = list((lc.get("counterfactual") or {}).get("horizons") or [1, 3, 5, 10, 20])
    modes = list((lc.get("counterfactual") or {}).get("entry_modes") or [])
    cache = ROOT / "data" / "cache" / "daily"
    # universe: focus fails + any parquet with recent limit-ups
    symbols = [s for s, _ in FOCUS_FAIL]
    extra = sorted(cache.glob("*.parquet"))[:80]
    for p in extra:
        sym = p.stem.replace("_", ".")
        if sym not in symbols and not sym.startswith("IDX"):
            symbols.append(sym)
        if len(symbols) >= 60:
            break

    per_sym = {}
    for sym in symbols:
        path = cache / f"{sym.replace('.', '_')}.parquet"
        if not path.exists():
            continue
        try:
            per_sym[sym] = analyze_symbol(path, horizons, modes)
        except Exception as exc:  # noqa: BLE001
            per_sym[sym] = {"error": str(exc)[:200]}

    # failure stock narrative
    failures = {}
    for sym, name in FOCUS_FAIL:
        row = per_sym.get(sym) or {}
        failures[sym] = {"name": name, "entries": row}

    summary = {
        "n_symbols": len(per_sym),
        "horizons": horizons,
        "modes": modes,
        "aggregate": aggregate({k: v for k, v in per_sym.items() if isinstance(v, dict) and "error" not in v}, modes, horizons),
        "failure_stocks": failures,
    }
    out = ROOT / "data" / "leader" / "entry_research_latest.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"n_symbols": summary["n_symbols"], "aggregate_keys": list(summary["aggregate"].keys())}, indent=2))
    # print best mode by t+5 mean among modes with n>=3
    best = None
    for mode, cell in summary["aggregate"].items():
        t5 = (cell.get("t+5") or {}) if isinstance(cell.get("t+5"), dict) else None
        if cell.get("n", 0) >= 3 and t5:
            score = t5["mean"] - 0.5 * abs(cell.get("t+5_mean_mdd") or 0)
            if best is None or score > best[0]:
                best = (score, mode, cell["n"], t5)
    if best:
        print(f"best_t+5_risk_adj: {best[1]} n={best[2]} mean={best[3]['mean']:.4f} win={best[3]['win_rate']:.2f}")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
