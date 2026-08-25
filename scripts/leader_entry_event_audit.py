#!/usr/bin/env python3
"""Audit PULLBACK exclusive vs HEALTHY_PULLBACK scan definitions; build unified dataset."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ashare.config import load_config
from ashare.leader.chase_risk import ChaseRiskEngine
from ashare.leader.entry_distribution import classify_pullback_health, round_trip_cost_buy_sell
from ashare.leader.entry_event_dataset import build_unified_dataset, make_event_id
from ashare.leader.entry_validation import (
    _consecutive_limit_up_series,
    build_symbol_samples,
    detect_entry_mode,
)
from ashare.leader.features import compute_leader_features
from ashare.leader.healthy_pullback_lab import is_pullback_day, scan_symbol_pullbacks
from ashare.leader.historical_limit_up import rebuild_daily_limit_up_index
from ashare.leader.pullback_features import compute_pullback_features
from ashare.leader.reentry_engine import ReentryEngine
from ashare.leader.stage_engine import StageEngine
from ashare.leader.trade_timing import TradeTimingEngine


def _row_key(symbol: str, date: str) -> str:
    return f"{symbol}|{date}"


def collect_exclusive_pullbacks(cache: Path, symbols: list[str], cfg) -> list[dict]:
    stage_e, chase_e, re_e, timing_e = StageEngine(cfg), ChaseRiskEngine(cfg), ReentryEngine(cfg), TradeTimingEngine(cfg)
    rows = []
    for sym in symbols:
        path = cache / f"{sym.replace('.', '_')}.parquet"
        if not path.exists():
            continue
        try:
            df = pd.read_parquet(path)
            samples = build_symbol_samples(df, sym, stage_e=stage_e, chase_e=chase_e, re_e=re_e, timing_e=timing_e)
            for s in samples:
                if s.entry_mode == "PULLBACK":
                    d = {
                        "symbol": s.symbol,
                        "date": s.date,
                        "entry_mode": s.entry_mode,
                        "board_count": s.board_count,
                        "stage": s.stage,
                        "source": "EXCLUSIVE_PULLBACK",
                        "t+1": (s.labels or {}).get("t+1"),
                        "t+3": (s.labels or {}).get("t+3"),
                        "t+5": (s.labels or {}).get("t+5"),
                    }
                    rows.append(d)
        except Exception:  # noqa: BLE001
            continue
    return rows


def collect_healthy_scan(cache: Path, symbols: list[str], cfg) -> list[dict]:
    cost = round_trip_cost_buy_sell(cfg)
    stage_e, chase_e, re_e = StageEngine(cfg), ChaseRiskEngine(cfg), ReentryEngine(cfg)
    rows = []
    for sym in symbols:
        path = cache / f"{sym.replace('.', '_')}.parquet"
        if not path.exists():
            continue
        try:
            df = pd.read_parquet(path)
            for r in scan_symbol_pullbacks(df, sym, cost_rate=cost, stage_e=stage_e, chase_e=chase_e, re_e=re_e):
                if r.get("pullback_health") == "HEALTHY_PULLBACK":
                    rows.append(
                        {
                            "symbol": r["symbol"],
                            "date": r["date"],
                            "entry_mode": "HEALTHY_PULLBACK_SCAN",
                            "board_count": r.get("board_count"),
                            "stage": r.get("stage"),
                            "pullback_depth": r.get("pullback_from_high"),
                            "health": r.get("pullback_health"),
                            "source": "HEALTHY_SCAN",
                            "entry_price": (r.get("labels") or {}).get("entry_price"),
                            "t+1": (r.get("labels") or {}).get("t+1"),
                            "t+3": (r.get("labels") or {}).get("t+3"),
                            "t+5": (r.get("labels") or {}).get("t+5"),
                        }
                    )
        except Exception:  # noqa: BLE001
            continue
    return rows


def enrich_exclusive(rows: list[dict], cache: Path) -> list[dict]:
    out = []
    for r in rows:
        path = cache / f"{r['symbol'].replace('.', '_')}.parquet"
        if not path.exists():
            out.append(r)
            continue
        df = pd.read_parquet(path)
        df["date"] = pd.to_datetime(df["date"])
        hist = df[df["date"].dt.normalize() <= pd.Timestamp(r["date"]).normalize()]
        feats = compute_leader_features(hist, as_of=r["date"])
        pb = compute_pullback_features(hist, as_of=r["date"], base_feats=feats or {})
        health = classify_pullback_health({**pb, "structure_score": 0.5, "pullback_score": 0.5, "volume_score": 0.5})
        r2 = dict(r)
        r2["pullback_depth"] = pb.get("pullback_from_high")
        r2["health"] = health
        r2["volume_ratio"] = pb.get("volume_ratio_to_peak")
        out.append(r2)
    return out


def write_audit_md(audit: dict, path: Path) -> None:
    lines = [
        "# PULLBACK DEFINITION AUDIT",
        "",
        "## Why n differs",
        "",
        audit["why_different"],
        "",
        f"- Exclusive PULLBACK n={audit['exclusive_n']} (symbols={audit['exclusive_symbols']})",
        f"- HEALTHY_PULLBACK scan n={audit['healthy_n']} (symbols={audit['healthy_symbols']})",
        f"- Intersection n={audit['intersection_n']}",
        f"- Only exclusive n={audit['only_exclusive_n']}",
        f"- Only healthy-scan n={audit['only_healthy_n']}",
        "",
        "## Definition differences",
        "",
        "### Exclusive PULLBACK (entry_validation.detect_entry_mode)",
        "",
        "- Universe: candidate days after 2+ board streak OR 3+ board limit-up",
        "- Mode exclusivity priority: REACCELERATION > REBREAKOUT > PULLBACK > FIRST_DIVERGENCE > DIRECT_CHASE",
        "- PULLBACK requires: not limit-up, days_since>=1, pullback_from_high in [-12%,-1.5%] AND volume_contraction>0.08 (or healthy_divergence)",
        "- If same day qualifies as REACCELERATION/REBREAKOUT, it is **not** counted as PULLBACK",
        "",
        "### HEALTHY_PULLBACK scan (healthy_pullback_lab)",
        "",
        "- Broader `is_pullback_day`: days_since 1..10 after 2+ streak, looser depth (-15%~-1% or -12%~-2%)",
        "- Then `classify_pullback_health` labels HEALTHY/DANGEROUS/NEUTRAL",
        "- **Does not** apply exclusive mode priority — days that would be REACCELERATION in exclusive set can still be HEALTHY_PULLBACK here",
        "- Used more symbols in prior runs (250 vs 120)",
        "",
        "## Overlap",
        "",
        f"- Duplicate events within exclusive: {audit['exclusive_dupes']}",
        f"- Duplicate events within healthy: {audit['healthy_dupes']}",
        "",
        "## Sample rows (intersection head)",
        "",
    ]
    for r in audit.get("intersection_samples") or []:
        lines.append(
            f"- {r.get('symbol')} {r.get('date')} board={r.get('board_count')} stage={r.get('stage')} "
            f"depth={r.get('pullback_depth')} health={r.get('health')} T+5={r.get('t+5')}"
        )
    lines += ["", "## Only exclusive (head)", ""]
    for r in audit.get("only_exclusive_samples") or []:
        lines.append(f"- {r.get('symbol')} {r.get('date')} health={r.get('health')} depth={r.get('pullback_depth')} T+5={r.get('t+5')}")
    lines += ["", "## Only healthy-scan (head)", ""]
    for r in audit.get("only_healthy_samples") or []:
        lines.append(f"- {r.get('symbol')} {r.get('date')} board={r.get('board_count')} depth={r.get('pullback_depth')} T+5={r.get('t+5')}")
    lines += [
        "",
        "## Conclusion",
        "",
        "- The two statistics are **not comparable** until unified on one EntryEvent dataset.",
        "- Do not optimize strategy from this mismatch.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    cfg = load_config()
    cfg["_root"] = str(ROOT)
    cache = ROOT / "data" / "cache" / "daily"

    # same symbol set for fair audit (all available)
    symbols = [p.stem.replace("_", ".") for p in sorted(cache.glob("*.parquet")) if not p.stem.startswith("IDX")]
    # audit uses up to 180 for speed; unified build uses all
    audit_syms = symbols[:180]

    print("collecting exclusive PULLBACK...")
    exclusive = collect_exclusive_pullbacks(cache, audit_syms, cfg)
    exclusive = enrich_exclusive(exclusive, cache)
    print("collecting HEALTHY scan...")
    healthy = collect_healthy_scan(cache, audit_syms, cfg)

    ex_keys = [_row_key(r["symbol"], r["date"]) for r in exclusive]
    hp_keys = [_row_key(r["symbol"], r["date"]) for r in healthy]
    ex_set, hp_set = set(ex_keys), set(hp_keys)
    inter = ex_set & hp_set
    only_ex = ex_set - hp_set
    only_hp = hp_set - ex_set

    ex_map = {_row_key(r["symbol"], r["date"]): r for r in exclusive}
    hp_map = {_row_key(r["symbol"], r["date"]): r for r in healthy}

    audit = {
        "exclusive_n": len(ex_set),
        "healthy_n": len(hp_set),
        "exclusive_symbols": len({r["symbol"] for r in exclusive}),
        "healthy_symbols": len({r["symbol"] for r in healthy}),
        "intersection_n": len(inter),
        "only_exclusive_n": len(only_ex),
        "only_healthy_n": len(only_hp),
        "exclusive_dupes": len(ex_keys) - len(ex_set),
        "healthy_dupes": len(hp_keys) - len(hp_set),
        "intersection_samples": [ex_map[k] for k in sorted(inter)[:25]],
        "only_exclusive_samples": [ex_map[k] for k in sorted(only_ex)[:25]],
        "only_healthy_samples": [hp_map[k] for k in sorted(only_hp)[:25]],
        "why_different": (
            "Exclusive PULLBACK is a **mutually exclusive entry mode** after mode priority; "
            "HEALTHY_PULLBACK is a **health label on a broader pullback-day scan** that ignores mode exclusivity. "
            f"On the same {len(audit_syms)} symbols: exclusive={len(ex_set)}, healthy-scan={len(hp_set)}, "
            f"intersection={len(inter)}."
        ),
    }
    audit_path = ROOT / "docs" / "research" / "PULLBACK_DEFINITION_AUDIT.md"
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    write_audit_md(audit, audit_path)
    (ROOT / "data" / "leader" / "pullback_definition_audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    print("wrote", audit_path)

    print("rebuilding historical limit-up index from bars...")
    lu_meta = rebuild_daily_limit_up_index(
        cache,
        out_path=ROOT / "data" / "cache" / "leader_history" / "limit_up_by_date.json",
        max_symbols=None,
    )
    print(lu_meta)

    print("building unified entry event dataset (all symbols)...")
    report = build_unified_dataset(root=ROOT, cfg=cfg, max_symbols=None)
    meta = report["meta"]

    # ENTRY_DATASET_REPORT.md
    ds_lines = [
        "# ENTRY DATASET REPORT",
        "",
        f"- events: **{meta.get('n_events')}**",
        f"- symbols: {meta.get('n_symbols_scanned')}",
        f"- trading days covered: {meta.get('n_trading_days_covered')} ({meta.get('date_start')} → {meta.get('date_end')})",
        f"- PRIMARY execution: **{meta.get('primary_execution')}**",
        f"- secondary: {meta.get('secondary_execution')}",
        f"- cost rate: {meta.get('cost_rate_round_trip')}",
        f"- LLM/ML/Token: {meta.get('llm_calls')}/{meta.get('ml_calls')}/{meta.get('tokens')}",
        f"- research scale (>=3000): {meta.get('research_scale_ok')}",
        f"- pullback edge verdict: **{report.get('pullback_edge_verdict')}**",
        "",
        "## By mode (PRIMARY = T+1 open net)",
        "",
    ]
    for m, cell in (report.get("by_mode") or {}).items():
        ds_lines.append(
            f"- **{m}**: n={cell.get('n')} quality={cell.get('sample_quality')} "
            f"net={cell.get('primary_net_mean')} win={cell.get('primary_net_win')} "
            f"LD={cell.get('limit_down_rate')} rar={cell.get('risk_adjusted_return')} "
            f"cc_ref={cell.get('secondary_cc_mean')}"
        )
    ds_lines += ["", "## Pullback by health (canonical PULLBACK events only)", ""]
    for h, cell in (report.get("pullback_by_health") or {}).items():
        ds_lines.append(
            f"- **{h}**: n={cell.get('n')} quality={cell.get('sample_quality')} "
            f"net={cell.get('primary_net_mean')} LD={cell.get('limit_down_rate')} rar={cell.get('risk_adjusted_return')}"
        )
    ds_lines += ["", "## By board", ""]
    for b, cell in (report.get("by_board") or {}).items():
        ds_lines.append(f"- {b}板: n={cell.get('n')} quality={cell.get('sample_quality')} net={cell.get('primary_net_mean')}")
    ds_lines += [
        "",
        "## Walk-forward (PULLBACK)",
        "",
        f"- {report.get('walk_forward_pullback')}",
        "",
        "## Notes",
        "",
        "- BUY pipeline unchanged.",
        "- reentry_score remains UNCALIBRATED / research-only.",
        "",
    ]
    ds_path = ROOT / "docs" / "research" / "ENTRY_DATASET_REPORT.md"
    ds_path.write_text("\n".join(ds_lines), encoding="utf-8")

    # ENTRY_EVENT_AUDIT.md
    ea = [
        "# ENTRY EVENT AUDIT",
        "",
        "## Answers",
        "",
        f"1. Why PULLBACK n=37 vs HEALTHY n=79? See PULLBACK_DEFINITION_AUDIT.md — exclusive mode vs broader health scan; "
        f"fair re-audit on {len(audit_syms)} symbols: exclusive={audit['exclusive_n']}, healthy-scan={audit['healthy_n']}, intersection={audit['intersection_n']}.",
        f"2. Duplicate events? exclusive_dupes={audit['exclusive_dupes']}, healthy_dupes={audit['healthy_dupes']}; unified dataset enforces one event per symbol-date.",
        "3. Future leakage? Features use as_of cut; tests/test_entry_event_leakage.py; health uses T-day structure/volume only.",
        f"4. Trading days covered: {meta.get('n_trading_days_covered')} ({meta.get('date_start')} → {meta.get('date_end')}).",
        f"5. Entry Event total: **{meta.get('n_events')}**.",
        f"6. Mode counts: { {m: (report.get('by_mode') or {}).get(m, {}).get('n') for m in (report.get('by_mode') or {})} }.",
        f"7. Board counts: { {b: (report.get('by_board') or {}).get(b, {}).get('n') for b in (report.get('by_board') or {})} }.",
        f"8. Research scale (>=3000)? **{meta.get('research_scale_ok')}**.",
        f"9. Any proven edge? **{report.get('pullback_edge_verdict')}**.",
        "10. Change BUY pipeline? **No** — research-only; thresholds frozen.",
        "",
        "## Limit-up history index",
        "",
        f"- {lu_meta}",
        "",
    ]
    (ROOT / "docs" / "research" / "ENTRY_EVENT_AUDIT.md").write_text("\n".join(ea), encoding="utf-8")

    print(
        {
            "audit_exclusive": audit["exclusive_n"],
            "audit_healthy": audit["healthy_n"],
            "intersection": audit["intersection_n"],
            "unified_events": meta.get("n_events"),
            "edge": report.get("pullback_edge_verdict"),
            "scale_ok": meta.get("research_scale_ok"),
            "llm": 0,
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
