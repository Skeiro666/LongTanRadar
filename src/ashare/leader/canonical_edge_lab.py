"""
Canonical leader universe + conditional edge mining (research-only).

- Does not change BUY gates / BUY_READY / LLM / ML / entry-mode weights
- PRIMARY execution remains T+1 open net
- board_count on pullback days is the originating streak length, not today's 0
"""
from __future__ import annotations

import json
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ashare.data.store import ParquetStore
from ashare.leader.entry_event_dataset import summarize_primary, walk_forward_primary
from ashare.leader.entry_validation import _consecutive_limit_up_series
from ashare.leader.pullback_features import compute_pullback_features

LEADER_LOOKBACK = 10
MIN_STREAK_BOARDS = 2
DIRECT_CHASE_BOARDS = 3

BOARD_GROUPS = ("1", "2", "3", "4", "5", "6", "7+")
DEPTH_GROUPS = ("-1%~-3%", "-3%~-5%", "-5%~-8%", "-8%~-12%", "<-12%")
VOLUME_GROUPS = ("强缩量", "中缩量", "轻缩量", "正常量", "放量")
STAGE_GROUPS = ("EARLY", "TREND", "ACCELERATION", "EXTREME", "DISTRIBUTION", "BREAKDOWN")
STRUCTURE_GROUPS = (
    "跌破关键高点",
    "跌破均线",
    "连续大阴",
    "当日跌停",
    "放量破位",
    "结构完好",
)


def research_sample_tier(n: int) -> str:
    if n < 30:
        return "INSUFFICIENT_SAMPLE"
    if n < 100:
        return "LOW_SAMPLE"
    if n < 300:
        return "OK"
    return "STRONG"


def board_group(bc: int) -> str:
    n = int(bc or 0)
    if n <= 0:
        return "0"
    if n >= 7:
        return "7+"
    return str(n)


def depth_group(dd: float | None) -> str | None:
    if dd is None:
        return None
    x = float(dd)
    if -0.03 <= x < -0.01:
        return "-1%~-3%"
    if -0.05 <= x < -0.03:
        return "-3%~-5%"
    if -0.08 <= x < -0.05:
        return "-5%~-8%"
    if -0.12 <= x < -0.08:
        return "-8%~-12%"
    if x < -0.12:
        return "<-12%"
    return None


def volume_group(vc: float | None) -> str:
    x = float(vc or 0)
    if x >= 0.40:
        return "强缩量"
    if x >= 0.25:
        return "中缩量"
    if x >= 0.08:
        return "轻缩量"
    if x >= -0.05:
        return "正常量"
    return "放量"


def last_limit_up_origin(
    lu: np.ndarray,
    boards: np.ndarray,
    i: int,
    *,
    lookback: int = LEADER_LOOKBACK,
) -> dict[str, Any]:
    """T-day origin: today's consecutive boards vs originating streak peak."""
    today_lu = bool(lu[i])
    today_board = int(boards[i]) if today_lu else 0
    last_j = None
    lo = max(0, i - lookback)
    for j in range(i, lo - 1, -1):
        if lu[j]:
            last_j = j
            break
    if last_j is None:
        return {
            "today_board": today_board,
            "leader_board_count": 0,
            "days_since_limit_up": None,
            "last_limit_up_idx": None,
            "leader_valid": False,
            "reject_reason": "NO_LIMIT_UP_IN_LOOKBACK",
        }
    peak = int(boards[last_j])
    days_since = int(i - last_j)
    if today_lu and today_board >= DIRECT_CHASE_BOARDS:
        valid, reason = True, None
    elif peak >= MIN_STREAK_BOARDS and 0 <= days_since <= lookback:
        valid, reason = True, None
    elif peak < MIN_STREAK_BOARDS:
        valid, reason = False, "PEAK_BOARD_LT_2"
    else:
        valid, reason = False, "STREAK_TOO_OLD"
    return {
        "today_board": today_board,
        "leader_board_count": peak,
        "days_since_limit_up": days_since,
        "last_limit_up_idx": last_j,
        "leader_valid": valid,
        "reject_reason": reason,
    }


def is_canonical_leader_event(origin: dict[str, Any], *, entry_mode: str, limit_up: bool) -> bool:
    if not origin.get("leader_valid"):
        return False
    peak = int(origin.get("leader_board_count") or 0)
    if peak <= 0:
        return False
    if entry_mode == "DIRECT_CHASE":
        return bool(limit_up) and int(origin.get("today_board") or 0) >= DIRECT_CHASE_BOARDS
    # pullback / first divergence / reaccel must come from a real streak, not ordinary names
    days = origin.get("days_since_limit_up")
    if days is None:
        return False
    if entry_mode in {"PULLBACK", "REACCELERATION", "REBREAKOUT", "FIRST_DIVERGENCE"}:
        return peak >= MIN_STREAK_BOARDS and 1 <= int(days) <= LEADER_LOOKBACK
    return peak >= MIN_STREAK_BOARDS


def _cell_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    out: dict[str, Any] = {
        "n": n,
        "sample_quality": research_sample_tier(n),
        "t1_net": None,
        "t3_net": None,
        "t5_net": None,
        "win": None,
        "ld": None,
        "mae": None,
        "mdd": None,
        "rar": None,
    }
    if n < 30:
        return out
    s1 = summarize_primary(rows, hz=1)
    s3 = summarize_primary(rows, hz=3)
    s5 = summarize_primary(rows, hz=5)
    out["t1_net"] = s1.get("primary_net_mean")
    out["t3_net"] = s3.get("primary_net_mean")
    out["t5_net"] = s5.get("primary_net_mean")
    out["win"] = s1.get("primary_net_win")
    out["ld"] = s1.get("limit_down_rate")
    out["mae"] = s1.get("mae_mean")
    out["mdd"] = s1.get("mdd_mean")
    out["rar"] = s1.get("risk_adjusted_return")
    return out


def _group_cells(rows: list[dict[str, Any]], key_fn, keys: tuple[str, ...]) -> dict[str, Any]:
    buckets: dict[str, list] = {k: [] for k in keys}
    other: list = []
    for r in rows:
        k = key_fn(r)
        if k in buckets:
            buckets[k].append(r)
        elif k is not None:
            other.append(r)
    out = {k: _cell_stats(v) for k, v in buckets.items()}
    if other:
        out["_other"] = _cell_stats(other)
    return out


def _cross(rows: list[dict[str, Any]], a_fn, a_keys, b_fn, b_keys) -> dict[str, Any]:
    grid: dict[str, Any] = {}
    for a in a_keys:
        for b in b_keys:
            part = [r for r in rows if a_fn(r) == a and b_fn(r) == b]
            grid[f"{a} × {b}"] = _cell_stats(part)
    return grid


def _structure_label(r: dict[str, Any]) -> str:
    flags = r.get("structure_flags") or {}
    if flags.get("limit_down_today"):
        return "当日跌停"
    if flags.get("volume_break"):
        return "放量破位"
    if flags.get("broke_key_high"):
        return "跌破关键高点"
    if flags.get("consecutive_big_red"):
        return "连续大阴"
    if flags.get("broke_ma"):
        return "跌破均线"
    return "结构完好"


def _annotate_from_bars(row: dict[str, Any], df: pd.DataFrame) -> dict[str, Any]:
    out = dict(row)
    if df is None or df.empty:
        out["origin"] = {
            "leader_valid": False,
            "reject_reason": "NO_BARS",
            "leader_board_count": 0,
            "today_board": int(row.get("board_count") or 0),
        }
        out["canonical"] = False
        return out
    frame = df.copy()
    frame["date"] = pd.to_datetime(frame["date"])
    frame = frame.sort_values("date").reset_index(drop=True)
    target = pd.Timestamp(str(row["date"])[:10]).normalize()
    dates = frame["date"].dt.normalize()
    hits = np.where(dates == target)[0]
    if len(hits) == 0 or "limit_up" not in frame.columns:
        out["origin"] = {
            "leader_valid": False,
            "reject_reason": "DATE_NOT_IN_BARS",
            "leader_board_count": 0,
            "today_board": int(row.get("board_count") or 0),
        }
        out["canonical"] = False
        return out
    i = int(hits[0])
    lu = frame["limit_up"].astype(bool).values
    boards = _consecutive_limit_up_series(lu)
    origin = last_limit_up_origin(lu, boards, i)
    out["origin"] = origin
    out["board_count_raw"] = int(row.get("board_count") or 0)
    out["board_count_today"] = int(origin["today_board"])
    out["board_count"] = int(origin["leader_board_count"] or 0)
    out["limit_up_today"] = bool(lu[i])
    out["canonical"] = is_canonical_leader_event(
        origin, entry_mode=str(row.get("entry_mode") or ""), limit_up=bool(lu[i])
    )
    if not out["canonical"]:
        out["exclude_reason"] = origin.get("reject_reason") or "NOT_LEADER_EVENT"
    hist = frame.iloc[: i + 1]
    pb = compute_pullback_features(hist, as_of=str(row["date"]))
    last = hist.iloc[-1]
    close = float(last["close"])
    ma20 = float(hist["close"].astype(float).tail(20).mean()) if len(hist) >= 20 else close
    dd = pb.get("pullback_from_high")
    out["pullback_depth"] = dd if dd is not None else out.get("pullback_depth")
    out["volume_contraction"] = pb.get("volume_contraction", out.get("volume_contraction"))
    out["volume_ratio"] = pb.get("volume_ratio_to_peak", out.get("volume_ratio"))
    out["structure_flags"] = {
        "broke_key_high": bool(float(pb.get("structure_break") or 0) >= 0.5 or float(dd or 0) < -0.08),
        "broke_ma": bool(ma20 > 0 and close < ma20 * 0.995),
        "consecutive_big_red": bool(float(pb.get("consecutive_down_days") or 0) >= 3 or float(pb.get("big_red_volume") or 0) >= 0.5),
        "limit_down_today": bool(last.get("limit_down")),
        "volume_break": bool(float(pb.get("volume_ratio_to_peak") or 0) >= 0.85 and float(dd or 0) < -0.05),
    }
    out["depth_group"] = depth_group(out.get("pullback_depth"))
    out["volume_group"] = volume_group(out.get("volume_contraction"))
    out["board_group"] = board_group(out["board_count"])
    out["structure_group"] = _structure_label(out)
    return out


def load_raw_events(root: Path) -> list[dict[str, Any]]:
    path = root / "data" / "cache" / "leader_history" / "entry_events" / "entry_events_latest.jsonl"
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def annotate_universe(root: Path, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    store = ParquetStore(root / "data" / "cache")
    by_sym: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_sym[str(r.get("symbol"))].append(r)
    out: list[dict[str, Any]] = []
    for sym, items in by_sym.items():
        df = store.load_daily(sym)
        for r in items:
            out.append(_annotate_from_bars(r, df))
    return out


def _count_jsonl_board0(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"available": False, "path": str(path)}
    n = n0 = n_healthy0 = 0
    example = None
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        n += 1
        if int(r.get("board_count") or 0) <= 0:
            n0 += 1
            if example is None and str(r.get("symbol")):
                example = {
                    "symbol": r.get("symbol"),
                    "date": r.get("date"),
                    "board_count": r.get("board_count"),
                    "stage": r.get("stage"),
                    "health": r.get("health"),
                    "entry_mode": r.get("entry_mode"),
                }
            if str(r.get("health")) == "HEALTHY_PULLBACK" or str(r.get("entry_mode")) == "PULLBACK":
                n_healthy0 += 1
    return {
        "available": True,
        "n": n,
        "board0": n0,
        "board0_pullback_like": n_healthy0,
        "example": example,
    }


def integrity_report(raw: list[dict[str, Any]], annotated: list[dict[str, Any]], *, root: Path) -> dict[str, Any]:
    n = len(raw)
    board0 = [r for r in raw if int(r.get("board_count") or 0) <= 0]
    board_ge1 = [r for r in raw if int(r.get("board_count") or 0) >= 1]
    breakdown_healthy = [
        r
        for r in raw
        if str(r.get("stage")) == "BREAKDOWN" and str(r.get("health")) == "HEALTHY_PULLBACK"
    ]
    valid = [r for r in annotated if r.get("canonical")]
    invalid = [r for r in annotated if not r.get("canonical")]
    repaired = [
        r
        for r in annotated
        if int(r.get("board_count_raw") or 0) <= 0 and int(r.get("board_count") or 0) >= MIN_STREAK_BOARDS
    ]
    still_zero = [r for r in annotated if int(r.get("board_count") or 0) <= 0]
    by_mode_pollution = {}
    modes = sorted({str(r.get("entry_mode")) for r in annotated})
    for m in modes:
        part = [r for r in annotated if r.get("entry_mode") == m]
        bad = [r for r in part if not r.get("canonical")]
        by_mode_pollution[m] = {
            "n": len(part),
            "non_leader": len(bad),
            "pollution_rate": (len(bad) / len(part)) if part else None,
        }
    examples = []
    for r in annotated:
        if int(r.get("board_count_raw") or 0) <= 0 and str(r.get("health")) == "HEALTHY_PULLBACK":
            examples.append(
                {
                    "symbol": r.get("symbol"),
                    "date": r.get("date"),
                    "board_raw": r.get("board_count_raw"),
                    "leader_board": r.get("board_count"),
                    "stage": r.get("stage"),
                    "health": r.get("health"),
                    "mode": r.get("entry_mode"),
                    "canonical": r.get("canonical"),
                    "reason": r.get("exclude_reason") or (r.get("origin") or {}).get("reject_reason"),
                }
            )
            if len(examples) >= 12:
                break
    return {
        "total_entry_events": n,
        "board_count_eq_0_raw": len(board0),
        "board_count_ge_1_raw": len(board_ge1),
        "board0_rate_raw": (len(board0) / n) if n else None,
        "breakdown_and_healthy_raw": len(breakdown_healthy),
        "leader_valid_events": len(valid),
        "non_leader_events": len(invalid),
        "pollution_rate": (len(invalid) / len(annotated)) if annotated else None,
        "repaired_peak_board_from_zero": len(repaired),
        "still_board_0_after_repair": len(still_zero),
        "by_mode_pollution": by_mode_pollution,
        "examples_board0_healthy": examples,
        "other_labs": {
            "entry_validation_samples": _count_jsonl_board0(
                root / "data" / "leader" / "entry_validation_samples.jsonl"
            ),
            "unified_jsonl_board0": len(board0),
        },
        "definitions": {
            "board_count_today": "当日连续涨停板数；非涨停日为 0",
            "leader_board_count": "最近一次涨停（回看10个交易日）当天的连续板数，即龙头波段板数",
            "canonical_rule": "DIRECT_CHASE 需当日连板>=3；回踩/分歧/再加速需 originating 连板>=2 且距最近涨停 1–10 日。board=0 默认 NOT_LEADER_EVENT",
            "healthy_pullback_lab": "独立扫描：10日内出现过 >=2 连板后的回踩日，不是 exclusive EntryMode，可能与统一事件集口径不同",
            "entry_validation": "与统一事件集同一候选窗（3板追涨 或 2板结束后12日），但板数曾误用当日 consecutive（回踩日=0）",
        },
        "answers": {
            "board_count_is_today_consecutive": "当日含义是连续涨停；旧数据集在回踩日经常写成 0，这是记录错误而不是普通股",
            "board0_allowed_in_old_dataset": True,
            "healthy_can_come_from_ordinary_stock": "旧口径可能：days_since_lu>=1 即使 peak 查找失败仍可打 PULLBACK。canonical 后不允许",
            "historical_universe_only_limit_up_leaders": "候选窗要求近期 2+ 连板或当日 3+ 板，但存储的 board_count=0 会让样本看起来像普通股",
        },
        "buy_pipeline_unchanged": True,
        "llm": 0,
        "ml": 0,
    }


def _collect_tests(cells: dict[str, Any]) -> list[dict[str, Any]]:
    tests = []
    for name, cell in cells.items():
        if not isinstance(cell, dict) or "n" not in cell:
            continue
        tests.append(
            {
                "name": name,
                "n": cell.get("n"),
                "t1_net": cell.get("t1_net"),
                "rar": cell.get("rar"),
                "ld": cell.get("ld"),
                "sample_quality": cell.get("sample_quality"),
            }
        )
    return tests


def _rank_cells(tests: list[dict[str, Any]]) -> dict[str, Any]:
    usable = [t for t in tests if t.get("t1_net") is not None]
    pos = [t for t in usable if float(t["t1_net"]) > 0]
    neg = [t for t in usable if float(t["t1_net"]) <= 0]
    ranked = sorted(usable, key=lambda t: float(t["t1_net"] or -9), reverse=True)
    med = None
    if usable:
        nets = sorted(float(t["t1_net"]) for t in usable)
        med = nets[len(nets) // 2]
        med_cell = min(usable, key=lambda t: abs(float(t["t1_net"]) - med))
    else:
        med_cell = None
    return {
        "total_tests": len(tests),
        "cells_with_stats": len(usable),
        "positive_cells": len(pos),
        "negative_cells": len(neg),
        "best_cell": ranked[0] if ranked else None,
        "second_best": ranked[1] if len(ranked) > 1 else None,
        "median_cell": med_cell,
        "median_t1_net": med,
        "multiple_testing_warning": "组合格点很多，单独最好看的格子不能当 Edge；n<100 只能 RESEARCH_SIGNAL",
    }


def mine_conditional(canonical: list[dict[str, Any]]) -> dict[str, Any]:
    healthy = [
        r
        for r in canonical
        if str(r.get("health")) == "HEALTHY_PULLBACK" and str(r.get("entry_mode")) == "PULLBACK"
    ]
    # also health-tagged healthy even if exclusive mode was stolen — still PULLBACK exclusive here
    def bg(r):
        return board_group(int(r.get("board_count") or 0))

    def dg(r):
        return r.get("depth_group")

    def vg(r):
        return r.get("volume_group")

    def sg(r):
        return str(r.get("stage") or "")

    def stg(r):
        return r.get("structure_group")

    board_cells = _group_cells(healthy, bg, BOARD_GROUPS)
    depth_cells = _group_cells(healthy, dg, DEPTH_GROUPS)
    vol_cells = _group_cells(healthy, vg, VOLUME_GROUPS)
    stage_cells = _group_cells(healthy, sg, STAGE_GROUPS)
    struct_cells = _group_cells(healthy, stg, STRUCTURE_GROUPS)
    crosses = {
        "BOARD × DEPTH": _cross(healthy, bg, BOARD_GROUPS, dg, DEPTH_GROUPS),
        "BOARD × VOLUME": _cross(healthy, bg, BOARD_GROUPS, vg, VOLUME_GROUPS),
        "BOARD × STAGE": _cross(healthy, bg, BOARD_GROUPS, sg, STAGE_GROUPS),
        "DEPTH × VOLUME": _cross(healthy, dg, DEPTH_GROUPS, vg, VOLUME_GROUPS),
        "STAGE × VOLUME": _cross(healthy, sg, STAGE_GROUPS, vg, VOLUME_GROUPS),
    }
    all_tests: list[dict[str, Any]] = []
    all_tests.extend(_collect_tests({f"BOARD={k}": v for k, v in board_cells.items()}))
    all_tests.extend(_collect_tests({f"DEPTH={k}": v for k, v in depth_cells.items()}))
    all_tests.extend(_collect_tests({f"VOLUME={k}": v for k, v in vol_cells.items()}))
    all_tests.extend(_collect_tests({f"STAGE={k}": v for k, v in stage_cells.items()}))
    all_tests.extend(_collect_tests({f"STRUCTURE={k}": v for k, v in struct_cells.items()}))
    for cname, grid in crosses.items():
        all_tests.extend(_collect_tests({f"{cname}:{k}": v for k, v in grid.items()}))
    mt = _rank_cells(all_tests)

    hopeful = [
        t
        for t in all_tests
        if int(t.get("n") or 0) >= 100
        and t.get("t1_net") is not None
        and float(t["t1_net"]) > 0
        and t.get("rar") is not None
        and float(t["rar"]) > 0
    ]
    hopeful.sort(key=lambda t: float(t["t1_net"]), reverse=True)

    wf_pack = []
    for t in hopeful[:5]:
        name = t["name"]
        subset = _rows_for_test_name(healthy, name)
        wf = walk_forward_primary(subset)
        wf["cell"] = name
        wf["n"] = len(subset)
        wf["t1_net_full"] = t.get("t1_net")
        wf_pack.append(wf)

    candidate_edge = False
    candidate_name = None
    for wf in wf_pack:
        splits = wf.get("splits") or {}
        nets = [splits.get(k, {}).get("primary_net_mean") for k in ("train", "validation", "test")]
        if any(x is None for x in nets):
            continue
        if not all(float(x) > 0 for x in nets):
            continue
        if not wf.get("all_positive"):
            continue
        n = int(wf.get("n") or 0)
        if n < 100:
            continue
        candidate_edge = True
        candidate_name = wf.get("cell")
        break

    verdict = "CANDIDATE_EDGE" if candidate_edge else "NO_EDGE_PROVEN"
    return {
        "n_healthy_pullback_canonical": len(healthy),
        "by_board": board_cells,
        "by_depth": depth_cells,
        "by_volume": vol_cells,
        "by_stage": stage_cells,
        "by_structure": struct_cells,
        "cross": crosses,
        "multiple_testing": mt,
        "hopeful_cells_n100": hopeful,
        "walk_forward": wf_pack,
        "verdict": verdict,
        "candidate_edge_cell": candidate_name,
        "news_note": "本阶段不把新闻写入 BUY；news 一律视为 research-unavailable",
        "buy_pipeline_should_stay": True,
    }


def _rows_for_test_name(rows: list[dict[str, Any]], name: str) -> list[dict[str, Any]]:
    if name.startswith("BOARD=") and " × " not in name:
        g = name.split("=", 1)[1]
        return [r for r in rows if board_group(int(r.get("board_count") or 0)) == g]
    if name.startswith("DEPTH="):
        g = name.split("=", 1)[1]
        return [r for r in rows if r.get("depth_group") == g]
    if name.startswith("VOLUME="):
        g = name.split("=", 1)[1]
        return [r for r in rows if r.get("volume_group") == g]
    if name.startswith("STAGE=") and " × " not in name:
        g = name.split("=", 1)[1]
        return [r for r in rows if str(r.get("stage")) == g]
    if name.startswith("STRUCTURE="):
        g = name.split("=", 1)[1]
        return [r for r in rows if r.get("structure_group") == g]
    if ":" in name:
        _, cell = name.split(":", 1)
        a, b = [x.strip() for x in cell.split("×")]
        if name.startswith("BOARD × DEPTH"):
            return [r for r in rows if board_group(int(r.get("board_count") or 0)) == a and r.get("depth_group") == b]
        if name.startswith("BOARD × VOLUME"):
            return [r for r in rows if board_group(int(r.get("board_count") or 0)) == a and r.get("volume_group") == b]
        if name.startswith("BOARD × STAGE"):
            return [r for r in rows if board_group(int(r.get("board_count") or 0)) == a and str(r.get("stage")) == b]
        if name.startswith("DEPTH × VOLUME"):
            return [r for r in rows if r.get("depth_group") == a and r.get("volume_group") == b]
        if name.startswith("STAGE × VOLUME"):
            return [r for r in rows if str(r.get("stage")) == a and r.get("volume_group") == b]
    return []


def _fmt_pct(x: Any) -> str:
    if x is None:
        return "—"
    return f"{float(x) * 100:.2f}%"


def _write_md_table(lines: list[str], cells: dict[str, Any]) -> None:
    lines.append("| 分组 | n | 样本 | T+1净 | T+3净 | T+5净 | 胜率 | 跌停率 | MAE | MDD | 风险调整 |")
    lines.append("|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for k, c in cells.items():
        if not isinstance(c, dict):
            continue
        lines.append(
            f"| {k} | {c.get('n')} | {c.get('sample_quality')} | {_fmt_pct(c.get('t1_net'))} | "
            f"{_fmt_pct(c.get('t3_net'))} | {_fmt_pct(c.get('t5_net'))} | {_fmt_pct(c.get('win'))} | "
            f"{_fmt_pct(c.get('ld'))} | {_fmt_pct(c.get('mae'))} | {_fmt_pct(c.get('mdd'))} | {_fmt_pct(c.get('rar'))} |"
        )


def write_reports(root: Path, integ: dict[str, Any], mine: dict[str, Any], canonical_n: int) -> None:
    docs = root / "docs" / "research"
    docs.mkdir(parents=True, exist_ok=True)
    ir = [
        "# 龙头宇宙完整性审计",
        "",
        "研究口径：PRIMARY = T+1 开盘买入净收益。未改 BUY 门槛、未调用大模型、未引入新 ML、未改 Entry Mode 权重。",
        "",
        "## 结论摘要",
        "",
        f"- 原始 EntryEvent：**{integ.get('total_entry_events')}**",
        f"- 原始 board_count=0：**{integ.get('board_count_eq_0_raw')}**（占比 {_fmt_pct(integ.get('board0_rate_raw'))}）",
        f"- 原始 board_count≥1：**{integ.get('board_count_ge_1_raw')}**",
        f"- BREAKDOWN 且 HEALTHY_PULLBACK：**{integ.get('breakdown_and_healthy_raw')}**",
        f"- 清洗后龙头有效事件：**{integ.get('leader_valid_events')}**",
        f"- 非龙头（剔除）：**{integ.get('non_leader_events')}**，污染率 {_fmt_pct(integ.get('pollution_rate'))}",
        f"- 从 board=0 修复出真实连板：**{integ.get('repaired_peak_board_from_zero')}**",
        f"- 修复后仍为 0（距最近涨停超过10日或找不到涨停）：**{integ.get('still_board_0_after_repair')}**",
        "",
        f"- 买点验证 jsonl：{integ.get('other_labs', {}).get('entry_validation_samples')}",
        "",
        "用户举例 `000620.SZ / 2025-12-01 / board=0 / BREAKDOWN` 来自 **entry_validation**：",
        "非涨停日用 `boards[i-1]`（前一日若不是涨停则为 0），没有回看最近一次涨停的连板。",
        "统一事件集 jsonl 里 board=0 为 0 条，因为它会回看最多 15 日找峰值连板；",
        "但候选窗是「2板结束后 12 日」，超过 10 日的回踩仍被 canonical 剔除。",
        "",
        "## board_count 定义",
        "",
        f"- 当日连板：{integ['definitions']['board_count_today']}",
        f"- 龙头波段板数：{integ['definitions']['leader_board_count']}",
        f"- Canonical 规则：{integ['definitions']['canonical_rule']}",
        "",
        "旧数据集在**回踩日**把 `consecutive_limit_up`（当日尾板为 0）写成 board_count，"
        "因此会出现 `board=0 + BREAKDOWN + HEALTHY_PULLBACK`。这不是「普通股进了龙头池」的充分证据，"
        "而是**板数字段用错了日期**。Canonical 一律改用 originating 连板。",
        "",
        "## 各模式污染率",
        "",
    ]
    for m, c in (integ.get("by_mode_pollution") or {}).items():
        ir.append(f"- **{m}**：n={c.get('n')} 非龙头={c.get('non_leader')} 污染率={_fmt_pct(c.get('pollution_rate'))}")
    ir += [
        "",
        "## 样本例子（旧 board=0 且 HEALTHY）",
        "",
        json.dumps(integ.get("examples_board0_healthy"), ensure_ascii=False, indent=2),
        "",
        "## 与其它实验室的差异",
        "",
        f"- healthy_pullback_lab：{integ['definitions']['healthy_pullback_lab']}",
        f"- entry_validation：{integ['definitions']['entry_validation']}",
        "",
        "## BUY 管线",
        "",
        "- 未修改。本文件只做研究清洗。",
        "",
    ]
    (docs / "LEADER_UNIVERSE_INTEGRITY_REPORT.md").write_text("\n".join(ir), encoding="utf-8")

    mt = mine.get("multiple_testing") or {}
    cr = [
        "# 条件边挖掘报告",
        "",
        f"- Canonical 龙头事件：**{canonical_n}**",
        f"- Canonical 回踩且 HEALTHY：**{mine.get('n_healthy_pullback_canonical')}**",
        f"- 总检验格点数：**{mt.get('total_tests')}**（有统计 {mt.get('cells_with_stats')}）",
        f"- 正收益格子：{mt.get('positive_cells')} · 负收益格子：{mt.get('negative_cells')}",
        f"- 最好格子：{mt.get('best_cell')}",
        f"- 次好格子：{mt.get('second_best')}",
        f"- 中位格子：{mt.get('median_cell')}",
        f"- **多重检验警告**：{mt.get('multiple_testing_warning')}",
        f"- 最终判定：**{mine.get('verdict')}**",
        f"- Candidate Edge 格子：{mine.get('candidate_edge_cell')}",
        f"- 新闻：{mine.get('news_note')}",
        f"- 是否应保持 BUY 管线不变：**是**",
        "",
        "## 健康回踩 × 连板",
        "",
    ]
    _write_md_table(cr, mine.get("by_board") or {})
    cr += ["", "## 健康回踩 × 回撤深度", ""]
    _write_md_table(cr, mine.get("by_depth") or {})
    cr += ["", "## 健康回踩 × 量能", ""]
    _write_md_table(cr, mine.get("by_volume") or {})
    cr += ["", "## 健康回踩 × 阶段", ""]
    _write_md_table(cr, mine.get("by_stage") or {})
    cr += ["", "## 健康回踩 × 价格结构（T 日可知）", ""]
    _write_md_table(cr, mine.get("by_structure") or {})
    cr += ["", "## 二维交叉（n<100 不得称 Edge）", ""]
    for cname, grid in (mine.get("cross") or {}).items():
        cr += [f"### {cname}", ""]
        _write_md_table(cr, grid)
        cr.append("")
    cr += ["", "## n≥100 且 T+1 净>0 且风险调整>0 的格子", ""]
    cr.append(json.dumps(mine.get("hopeful_cells_n100"), ensure_ascii=False, indent=2, default=str))
    cr += ["", "## Walk-forward", ""]
    cr.append(json.dumps(mine.get("walk_forward"), ensure_ascii=False, indent=2, default=str))
    cr += [
        "",
        "## 必须回答的问题",
        "",
        f"1. 8863 里多少是真正龙头？清洗后 **{integ.get('leader_valid_events')}**。",
        f"2. board=0 为什么存在？回踩日误用当日 consecutive_limit_up=0；其中 {integ.get('repaired_peak_board_from_zero')} 条可修复为真实连板。",
        "3. 是否有普通股票污染？旧集可能混入查找失败的事件；canonical 已剔除无法证明 2 连板来源的样本。",
        f"4. 清洗后还剩多少？**{canonical_n}**。",
        "5. PULLBACK 哪些条件最好？见多重检验 best/second/median，禁止只看最好格子。",
        f"6. 是否存在 n≥100 的正 EV 格子？**{len(mine.get('hopeful_cells_n100') or [])}** 个满足 n≥100 且 T+1 净>0 且 RAR>0。",
        f"7. Walk-forward 是否仍成立？见上文；判定={mine.get('verdict')}。",
        f"8. 是否存在真正 Candidate Edge？**{'是' if mine.get('verdict')=='CANDIDATE_EDGE' else '否'}**。",
        "9. 当前 BUY pipeline 是否应保持不变？**是。**",
        "",
    ]
    (docs / "CONDITIONAL_EDGE_REPORT.md").write_text("\n".join(cr), encoding="utf-8")


def run_lab(root: Path) -> dict[str, Any]:
    t0 = time.time()
    raw = load_raw_events(root)
    if not raw:
        raise RuntimeError("找不到 entry_events_latest.jsonl，请先跑统一事件集")
    annotated = annotate_universe(root, raw)
    integ = integrity_report(raw, annotated, root=root)
    canonical = [r for r in annotated if r.get("canonical")]
    mine = mine_conditional(canonical)

    canon_path = root / "data" / "cache" / "leader_history" / "entry_events" / "canonical_leader_events.jsonl"
    canon_path.parent.mkdir(parents=True, exist_ok=True)
    slim = []
    for r in canonical:
        slim.append(
            {
                "event_id": r.get("event_id"),
                "symbol": r.get("symbol"),
                "date": r.get("date"),
                "entry_mode": r.get("entry_mode"),
                "health": r.get("health"),
                "stage": r.get("stage"),
                "board_count": r.get("board_count"),
                "board_count_raw": r.get("board_count_raw"),
                "board_count_today": r.get("board_count_today"),
                "pullback_depth": r.get("pullback_depth"),
                "volume_contraction": r.get("volume_contraction"),
                "depth_group": r.get("depth_group"),
                "volume_group": r.get("volume_group"),
                "structure_group": r.get("structure_group"),
                "structure_flags": r.get("structure_flags"),
                "labels": r.get("labels"),
            }
        )
    canon_path.write_text("\n".join(json.dumps(x, ensure_ascii=False, default=str) for x in slim), encoding="utf-8")

    payload = {
        "available": True,
        "meta": {
            "elapsed_sec": round(time.time() - t0, 2),
            "raw_events": len(raw),
            "canonical_events": len(canonical),
            "primary_execution": "T+1_open_net",
            "buy_pipeline_unchanged": True,
            "llm_calls": 0,
            "ml_calls": 0,
            "tokens": 0,
            "canonical_path": str(canon_path.relative_to(root)).replace("\\", "/"),
        },
        "integrity": integ,
        "mining": mine,
    }
    latest = root / "data" / "leader" / "conditional_edge_latest.json"
    latest.parent.mkdir(parents=True, exist_ok=True)
    latest.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    write_reports(root, integ, mine, len(canonical))
    return payload
