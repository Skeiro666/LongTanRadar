"""
Unified Entry Event Dataset (research-only).

Canonical rule:
- One (symbol, date) → at most one EntryEvent
- Features: T close and earlier only
- Labels: future path only (PRIMARY = T+1 open net)
- No BUY pipeline wiring; no LLM/ML; params frozen
"""
from __future__ import annotations

import hashlib
import json
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

from ashare.leader.chase_risk import ChaseRiskEngine
from ashare.leader.entry_distribution import (
    classify_pullback_health,
    round_trip_cost_buy_sell,
)
from ashare.leader.entry_validation import (
    ENTRY_MODES,
    HORIZONS,
    _consecutive_limit_up_series,
    detect_entry_mode,
)
from ashare.leader.features import compute_leader_features
from ashare.leader.healthy_pullback_lab import is_pullback_day
from ashare.leader.pullback_features import compute_pullback_features
from ashare.leader.reentry_engine import ReentryEngine
from ashare.leader.stage_engine import StageEngine


def sample_quality_tier(n: int) -> str:
    if n < 15:
        return "INSUFFICIENT_SAMPLE"
    if n < 30:
        return "LOW_SAMPLE"
    if n < 100:
        return "OK"
    return "STRONG_SAMPLE"


@dataclass
class EntryEvent:
    event_id: str
    symbol: str
    date: str
    board_count: int
    stage: str
    entry_mode: str
    entry_price: float  # T+1 open (execution)
    signal_close: float  # T close
    pullback_depth: float | None
    volume_ratio: float | None
    volume_contraction: float | None
    structure_score: float
    reacceleration_score: float
    chase_score: float
    leader_score: float
    health: str
    reentry_score: float
    reentry_score_status: str = "REENTRY_SCORE_UNCALIBRATED"
    labels: dict[str, Any] = field(default_factory=dict)


def make_event_id(symbol: str, date: str, mode: str) -> str:
    raw = f"{symbol}|{date}|{mode}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _fwd_labels_primary(df: pd.DataFrame, i: int, *, cost_rate: float) -> dict[str, Any]:
    """PRIMARY = T+1 open fill → T+h close; also store close-to-close as secondary."""
    c = df["close"].astype(float).values
    o = df["open"].astype(float).values if "open" in df.columns else c
    h = df["high"].astype(float).values if "high" in df.columns else c
    lo = df["low"].astype(float).values if "low" in df.columns else c
    ld = df["limit_down"].astype(bool).values if "limit_down" in df.columns else np.zeros(len(df), dtype=bool)
    out: dict[str, Any] = {"primary_execution": "T+1_open_net", "secondary": "close_to_close"}
    if i + 1 >= len(df):
        return out
    entry = float(o[i + 1])
    signal_close = float(c[i])
    if entry <= 0 or signal_close <= 0:
        return out
    out["entry_price"] = entry
    out["signal_close"] = signal_close
    out["gap_open"] = float(entry / signal_close - 1.0)
    out["cost_rate"] = cost_rate
    # MFE/MAE vs entry (labels)
    max_h = max(HORIZONS)
    j_end = min(len(c) - 1, i + max_h)
    if j_end > i:
        path_h = h[i + 1 : j_end + 1]
        path_lo = lo[i + 1 : j_end + 1]
        if len(path_h):
            out["mfe"] = float(np.max(path_h) / entry - 1.0)
            out["mae"] = float(np.min(path_lo) / entry - 1.0)
        run = np.concatenate([[entry], c[i + 1 : j_end + 1]])
        peak = np.maximum.accumulate(run)
        out["mdd"] = float(np.min(run / peak - 1.0))
    for hz in HORIZONS:
        exit_i = i + hz
        if exit_i >= len(c):
            out[f"t+{hz}_gross"] = None
            out[f"t+{hz}_net"] = None
            out[f"t+{hz}_cc"] = None
            out[f"t+{hz}_limit_down"] = None
            continue
        gross = float(c[exit_i] / entry - 1.0)
        out[f"t+{hz}_gross"] = gross
        out[f"t+{hz}_net"] = float(gross - cost_rate)
        out[f"t+{hz}_cc"] = float(c[exit_i] / signal_close - 1.0)  # secondary
        out[f"t+{hz}_limit_down"] = bool(ld[i + 1 : exit_i + 1].any())
    return out


def build_events_for_symbol(
    df: pd.DataFrame,
    symbol: str,
    *,
    cost_rate: float,
    stage_e: StageEngine,
    chase_e: ChaseRiskEngine,
    re_e: ReentryEngine,
    min_history: int = 65,
) -> list[EntryEvent]:
    frame = df.copy()
    frame["date"] = pd.to_datetime(frame["date"])
    frame = frame.sort_values("date").reset_index(drop=True)
    if "limit_up" not in frame.columns or len(frame) < min_history + 5:
        return []
    lu = frame["limit_up"].astype(bool).values
    boards = _consecutive_limit_up_series(lu)
    events: list[EntryEvent] = []

    candidates: set[int] = set()
    for i, b in enumerate(boards):
        if i < min_history or i + 1 >= len(frame):
            continue
        if lu[i] and b >= 3:
            candidates.add(i)
        if (not lu[i]) and i > 0 and boards[i - 1] >= 2:
            for k in range(i, min(len(frame) - 1, i + 12)):
                if k >= min_history:
                    candidates.add(k)

    for i in sorted(candidates):
        as_of = str(frame["date"].iloc[i].date())
        hist = frame.iloc[: i + 1]
        feats = compute_leader_features(hist, as_of=as_of)
        if not feats:
            continue
        board_now = int(feats.get("consecutive_limit_up") or boards[i])
        if lu[i]:
            board_for_mode = board_now
        else:
            board_for_mode = 0
            for j in range(i - 1, max(-1, i - 15), -1):
                if lu[j]:
                    board_for_mode = int(boards[j])
                    break
            if board_for_mode <= 0 and i > 0:
                board_for_mode = int(boards[i - 1]) or board_now
        stage = stage_e.classify(feats, {"board_count": board_for_mode})
        chase = float(chase_e.score(feats, stage=stage))
        pb = compute_pullback_features(hist, as_of=as_of, base_feats=feats)
        re = re_e.evaluate(
            {**feats, **pb},
            stage=stage,
            chase_score=chase,
            limit_up=bool(lu[i]),
            as_of=as_of,
            bars=None,
        )
        days_since = int(float(pb.get("days_since_limit_up") or 0))
        first_non = days_since == 1 and (not lu[i]) and i > 0 and boards[i - 1] >= 2
        mode = detect_entry_mode(
            limit_up=bool(lu[i]),
            board=board_for_mode,
            first_non_lu=first_non,
            days_since_lu=0 if lu[i] else days_since,
            pb=pb,
            re_phase=str(re.get("reentry_phase") or ""),
        )
        if mode is None:
            continue
        labels = _fwd_labels_primary(frame, i, cost_rate=cost_rate)
        if labels.get("t+1_net") is None:
            continue
        comps = re.get("reentry_components") or {}
        # health only on pullback-like days; else NA
        health_row = {
            **pb,
            "structure_score": float(comps.get("structure_score") or 0),
            "pullback_score": float(comps.get("pullback_score") or 0),
            "volume_score": float(comps.get("volume_score") or 0),
        }
        if mode == "PULLBACK" or is_pullback_day(pb, days_since_lu=days_since, limit_up=bool(lu[i])):
            health = classify_pullback_health(health_row)
        else:
            health = "NA"

        ev = EntryEvent(
            event_id=make_event_id(symbol, as_of, mode),
            symbol=symbol,
            date=as_of,
            board_count=board_for_mode,
            stage=stage,
            entry_mode=mode,
            entry_price=float(labels.get("entry_price") or 0),
            signal_close=float(labels.get("signal_close") or frame["close"].astype(float).iloc[i]),
            pullback_depth=pb.get("pullback_from_high"),
            volume_ratio=pb.get("volume_ratio_to_peak"),
            volume_contraction=pb.get("volume_contraction"),
            structure_score=float(comps.get("structure_score") or 0),
            reacceleration_score=float(comps.get("reacceleration_score") or 0),
            chase_score=chase,
            leader_score=min(1.0, board_for_mode / 5.0),
            health=health,
            reentry_score=float(re.get("reentry_score") or 0),
            labels=labels,
        )
        events.append(ev)

    # enforce one event per symbol-date (keep first by mode priority already in detect)
    by_day: dict[str, EntryEvent] = {}
    for ev in events:
        key = f"{ev.symbol}|{ev.date}"
        if key not in by_day:
            by_day[key] = ev
    return list(by_day.values())


def summarize_primary(rows: list[dict[str, Any]], *, hz: int = 5) -> dict[str, Any]:
    n = len(rows)
    tier = sample_quality_tier(n)
    out: dict[str, Any] = {"n": n, "sample_quality": tier}
    if n < 15:
        return out
    nets = [r["labels"].get(f"t+{hz}_net") for r in rows if r["labels"].get(f"t+{hz}_net") is not None]
    gross = [r["labels"].get(f"t+{hz}_gross") for r in rows if r["labels"].get(f"t+{hz}_gross") is not None]
    ccs = [r["labels"].get(f"t+{hz}_cc") for r in rows if r["labels"].get(f"t+{hz}_cc") is not None]
    lds = [r["labels"].get(f"t+{hz}_limit_down") for r in rows if r["labels"].get(f"t+{hz}_limit_down") is not None]
    maes = [r["labels"].get("mae") for r in rows if r["labels"].get("mae") is not None]
    mdds = [r["labels"].get("mdd") for r in rows if r["labels"].get("mdd") is not None]
    if not nets:
        return out
    arr = np.array(nets, dtype=float)
    garr = np.array(gross, dtype=float) if gross else arr
    carr = np.array(ccs, dtype=float) if ccs else arr
    out.update(
        {
            "primary_net_mean": float(arr.mean()),
            "primary_net_median": float(np.median(arr)),
            "primary_net_win": float((arr > 0).mean()),
            "primary_gross_mean": float(garr.mean()),
            "secondary_cc_mean": float(carr.mean()),
            "limit_down_rate": float(np.mean(lds)) if lds else None,
            "mae_mean": float(np.mean(maes)) if maes else None,
            "mdd_mean": float(np.mean(mdds)) if mdds else None,
            "p10": float(np.percentile(arr, 10)),
            "p90": float(np.percentile(arr, 90)),
        }
    )
    # risk-adjusted on PRIMARY net
    ld = float(out["limit_down_rate"] or 0)
    mdd = abs(float(out["mdd_mean"] or 0))
    out["risk_adjusted_return"] = float(out["primary_net_mean"] - 0.35 * ld - 0.50 * mdd)
    return out


def correlation_matrix(rows: list[dict[str, Any]]) -> dict[str, Any]:
    feats = ["pullback_depth", "volume_ratio", "structure_score", "board_count", "chase_score", "reacceleration_score"]
    # map
    data = []
    for r in rows:
        lab = r.get("labels") or {}
        data.append(
            {
                "pullback_depth": r.get("pullback_depth"),
                "volume_ratio": r.get("volume_ratio"),
                "structure_score": r.get("structure_score"),
                "board_count": r.get("board_count"),
                "chase_score": r.get("chase_score"),
                "reacceleration_score": r.get("reacceleration_score"),
                "t5_net": lab.get("t+5_net"),
                "t10_net": lab.get("t+10_net"),
                "mdd": lab.get("mdd"),
                "mae": lab.get("mae"),
                "ld5": 1.0 if lab.get("t+5_limit_down") else 0.0 if lab.get("t+5_limit_down") is not None else None,
            }
        )
    df = pd.DataFrame(data).dropna()
    if len(df) < 30:
        return {"status": "INSUFFICIENT_SAMPLE", "n": len(df)}
    targets = ["t5_net", "t10_net", "mdd", "mae", "ld5"]
    out = {"n": len(df), "status": "OK", "spearman": {}}
    for f in feats:
        out["spearman"][f] = {}
        for t in targets:
            try:
                corr = float(df[f].corr(df[t], method="spearman"))
            except Exception:  # noqa: BLE001
                corr = None
            out["spearman"][f][t] = corr
    return out


def walk_forward_primary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if len(rows) < 30:
        return {"status": "INSUFFICIENT_SAMPLE", "n": len(rows)}
    ordered = sorted(rows, key=lambda r: r["date"])
    n = len(ordered)
    i1, i2 = int(n * 0.6), int(n * 0.8)
    splits = {"train": ordered[:i1], "validation": ordered[i1:i2], "test": ordered[i2:]}
    out: dict[str, Any] = {"status": "OK", "n": n, "splits": {}}
    nets = {}
    for name, part in splits.items():
        s = summarize_primary(part)
        out["splits"][name] = {
            "n": len(part),
            "date_start": part[0]["date"] if part else None,
            "date_end": part[-1]["date"] if part else None,
            "sample_quality": s.get("sample_quality"),
            "primary_net_mean": s.get("primary_net_mean"),
            "limit_down_rate": s.get("limit_down_rate"),
            "risk_adjusted_return": s.get("risk_adjusted_return"),
        }
        nets[name] = s.get("primary_net_mean")
    # at least two segments same sign
    signs = [1 if (nets.get(k) or 0) > 0 else -1 for k in ("train", "validation", "test") if nets.get(k) is not None]
    out["two_segments_same_sign"] = len(signs) >= 2 and (signs.count(1) >= 2 or signs.count(-1) >= 2)
    out["all_positive"] = all((nets.get(k) or 0) > 0 for k in ("train", "validation", "test") if nets.get(k) is not None)
    return out


def pullback_edge_verdict(cell: dict[str, Any], wf: dict[str, Any]) -> str:
    n = int(cell.get("n") or 0)
    net = cell.get("primary_net_mean")
    rar = cell.get("risk_adjusted_return")
    ld = cell.get("limit_down_rate")
    if n < 100:
        return "NO_EDGE_PROVEN"
    if net is None or net <= 0:
        return "NO_EDGE_PROVEN"
    if rar is None or rar <= 0:
        return "NO_EDGE_PROVEN"
    if ld is None or ld > 0.20:
        return "NO_EDGE_PROVEN"
    if not wf.get("two_segments_same_sign"):
        return "NO_EDGE_PROVEN"
    return "PULLBACK_EDGE_SUPPORTED"


def build_unified_dataset(
    *,
    root: Path,
    cfg: dict[str, Any] | None = None,
    max_symbols: int | None = None,
) -> dict[str, Any]:
    t0 = time.time()
    cost_rate = round_trip_cost_buy_sell(cfg)
    cache = root / "data" / "cache" / "daily"
    hist_dir = root / "data" / "cache" / "leader_history" / "entry_events"
    hist_dir.mkdir(parents=True, exist_ok=True)

    paths = sorted(p for p in cache.glob("*.parquet") if not p.stem.startswith("IDX"))
    if max_symbols:
        paths = paths[: max_symbols]

    stage_e, chase_e, re_e = StageEngine(cfg), ChaseRiskEngine(cfg), ReentryEngine(cfg)
    all_events: list[EntryEvent] = []
    errors = []
    dates = set()
    for p in paths:
        sym = p.stem.replace("_", ".")
        try:
            df = pd.read_parquet(p)
            evs = build_events_for_symbol(df, sym, cost_rate=cost_rate, stage_e=stage_e, chase_e=chase_e, re_e=re_e)
            all_events.extend(evs)
            for e in evs:
                dates.add(e.date)
        except Exception as exc:  # noqa: BLE001
            errors.append({"symbol": sym, "error": str(exc)[:160]})

    # dedupe by event_id
    uniq = {e.event_id: e for e in all_events}
    events = list(uniq.values())
    rows = [asdict(e) for e in events]

    # persist jsonl
    jsonl_path = hist_dir / "entry_events_latest.jsonl"
    jsonl_path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False, default=str) for r in rows),
        encoding="utf-8",
    )

    by_mode = {m: [r for r in rows if r["entry_mode"] == m] for m in ENTRY_MODES}
    mode_stats = {m: summarize_primary(rs) for m, rs in by_mode.items()}

    # health on PULLBACK events only (canonical)
    pb_rows = by_mode.get("PULLBACK") or []
    health_stats = {
        h: summarize_primary([r for r in pb_rows if r.get("health") == h])
        for h in ("HEALTHY_PULLBACK", "DANGEROUS_PULLBACK", "NEUTRAL_PULLBACK")
    }
    # also all events with health tag for comparison
    health_all = {
        h: summarize_primary([r for r in rows if r.get("health") == h])
        for h in ("HEALTHY_PULLBACK", "DANGEROUS_PULLBACK", "NEUTRAL_PULLBACK")
    }

    board_stats = {}
    for b in ("1", "2", "3", "4", "5", "6+"):
        def _bucket(bc: int) -> str:
            if bc <= 1:
                return "1"
            if bc >= 6:
                return "6+"
            return str(bc)

        board_stats[b] = summarize_primary([r for r in rows if _bucket(int(r["board_count"])) == b])

    corr = correlation_matrix(rows)
    wf_pb = walk_forward_primary(pb_rows)
    wf_hp = walk_forward_primary([r for r in pb_rows if r.get("health") == "HEALTHY_PULLBACK"])
    edge = pullback_edge_verdict(mode_stats.get("PULLBACK") or {}, wf_pb)

    date_list = sorted(dates)
    report = {
        "meta": {
            "n_symbols_scanned": len(paths),
            "n_events": len(rows),
            "n_trading_days_covered": len(date_list),
            "date_start": date_list[0] if date_list else None,
            "date_end": date_list[-1] if date_list else None,
            "elapsed_sec": round(time.time() - t0, 2),
            "llm_calls": 0,
            "tokens": 0,
            "ml_calls": 0,
            "primary_execution": "T+1_open_net",
            "secondary_execution": "close_to_close",
            "cost_rate_round_trip": cost_rate,
            "reentry_score_status": "REENTRY_SCORE_UNCALIBRATED",
            "buy_pipeline_unchanged": True,
            "research_scale_ok": len(rows) >= 3000,
            "events_path": str(jsonl_path.relative_to(root)).replace("\\", "/"),
        },
        "by_mode": mode_stats,
        "by_board": board_stats,
        "pullback_by_health": health_stats,
        "all_events_by_health": health_all,
        "correlation": corr,
        "walk_forward_pullback": wf_pb,
        "walk_forward_healthy_pullback": wf_hp,
        "pullback_edge_verdict": edge,
        "errors_head": errors[:10],
    }
    out_json = root / "data" / "leader" / "entry_dataset_latest.json"
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return report
