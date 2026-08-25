#!/usr/bin/env python3
"""Summarize leader pipeline vs legacy audit metrics from latest report."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def main() -> int:
    report = _load_json(ROOT / "data" / "reports" / "latest.json")
    dry = _load_json(ROOT / "data" / "leader" / "dry_run_latest.json")
    entry = _load_json(ROOT / "data" / "leader" / "entry_research_latest.json")
    usage_path = ROOT / "data" / "ai" / "usage.jsonl"
    usage_lines = usage_path.read_text(encoding="utf-8").strip().splitlines() if usage_path.exists() else []
    cycle_id = (report.get("ai_cost") or {}).get("cycle_id")
    cycle_tokens = 0
    council_calls = 0
    for line in usage_lines[-500:]:
        try:
            row = json.loads(line)
        except Exception:
            continue
        if cycle_id and row.get("cycle_id") == cycle_id:
            cycle_tokens += int(row.get("total_tokens") or 0)
            if "council" in str(row.get("call_site") or ""):
                council_calls += 1

    cu = report.get("candidate_union") or {}
    lp = cu.get("leader_pipeline") or {}
    lm = report.get("leader_monitor") or {}
    if not lp and dry:
        lp = {
            "leader_rejected": dry.get("leader_rejected"),
            "focus_stats": dry.get("focus_stats"),
            "dashboard": (dry.get("leader_monitor") or {}).get("stage_performance"),
        }
        cu = {
            "n_union": dry.get("n_enriched"),
            "n_research": dry.get("n_research"),
        }
    if (not lm or not lm.get("focus_watchlist")) and dry.get("leader_monitor"):
        lm = dry["leader_monitor"]
    as_of = report.get("as_of") or dry.get("as_of")
    decisions = report.get("canonical_decisions") or []
    buy_n = sum(1 for d in decisions if d.get("committee_approve"))
    timing_ready = sum(
        1 for d in decisions if (d.get("leader_timing") or {}).get("trade_timing_action") == "BUY_READY"
    )
    buckets = lm.get("buckets") or {}
    timing_counts = dry.get("timing_counts") or {}
    reentry_counts = dry.get("reentry_phase_counts") or {}

    print("=== LongTanRadar Leader Pipeline Summary ===")
    print(f"as_of: {as_of}")
    print(f"leader_version: {(dry.get('leader_version') or lm.get('leader_version') or 'leader_v2')}")
    print(f"positioning: {(lm.get('positioning') or '涨停龙头')}")
    if dry and not (report.get("candidate_union") or {}).get("leader_pipeline"):
        print("source: dry_run_latest.json (full research cycle pending / news LLM slow)")
    print()
    print("--- Pipeline layers ---")
    print(f"pool_size: {(report.get('screen') or {}).get('filtered_count')}")
    print(f"leader_rejected (NOT_LIMIT_UP): {lp.get('leader_rejected')}")
    print(f"union: {cu.get('n_union')} -> research: {cu.get('n_research')}")
    print(f"focus_stats: {lp.get('focus_stats')}")
    print()
    print("--- Leader monitor ---")
    print(f"message: {lm.get('message')}")
    for k in ("BUY_READY", "BUY_CANDIDATE", "FOCUS", "WAIT", "DROPPED"):
        print(f"  {k}: {len(buckets.get(k) or [])}")
    print()
    print("--- Timing / Re-entry (dry-run) ---")
    print(f"timing_counts: {timing_counts}")
    print(f"reentry_phase_counts: {reentry_counts}")
    print(f"buy_candidate_n: {dry.get('buy_candidate_n')} buy_ready_n: {dry.get('buy_ready_n')}")
    print()
    print("--- BUY / Timing ---")
    print(f"canonical BUY (committee_approve): {buy_n}")
    print(f"trade_timing BUY_READY (research): {timing_ready}")
    print(f"research_only: {lm.get('research_only')}")
    print()
    print("--- Token (this cycle) ---")
    print(f"cycle_id: {cycle_id}")
    print(f"cycle_tokens (usage.jsonl): {cycle_tokens}")
    print(f"council_calls: {council_calls}")
    ai_cost = report.get("ai_cost") or {}
    print(f"ai_cost summary: {ai_cost.get('total_tokens')} tokens, ${ai_cost.get('estimated_cost_usd')}")
    print()
    print("--- Before (leader_v1 2026-08-25) vs After (leader_v2 reentry) ---")
    print("  Before: BUY_READY=0  BUY=0  Focus=8  BUY_CANDIDATE=0  LLM=0  Token=0")
    print(
        f"  After:  BUY_READY={len(buckets.get('BUY_READY') or [])}  "
        f"BUY={buy_n}  Focus={len(buckets.get('FOCUS') or [])}  "
        f"BUY_CANDIDATE={len(buckets.get('BUY_CANDIDATE') or [])}  "
        f"LLM={council_calls}  Token={cycle_tokens or ai_cost.get('total_tokens') or 0}"
    )
    print("  Why: Re-entry unlocks BUY_CANDIDATE only when structure improves; EXTREME chase still WAIT;")
    print("       thresholds not lowered; board<2 cannot BUY_*; dry-run still 0 LLM (rules_only).")
    if entry.get("aggregate"):
        print()
        print("--- Entry research (sample) ---")
        for mode in ("board_3", "board_4", "board_5", "extreme_chase", "first_divergence", "reacceleration"):
            cell = (entry.get("aggregate") or {}).get(mode) or {}
            t5 = cell.get("t+5") or {}
            if isinstance(t5, dict) and t5.get("mean") is not None:
                print(
                    f"  {mode}: n={cell.get('n')} t+5={t5.get('mean'):+.3f} "
                    f"win={t5.get('win_rate'):.0%} ld5={cell.get('t+5_limit_down_rate')}"
                )
    print()
    print("--- Remaining risks ---")
    print("  1. research_only=true — canonical BUY unchanged until validation complete")
    print("  2. BUY_READY needs TREND/EARLY + board>=2 + high timing (not EXTREME label)")
    print("  3. T-day limit_up still blocks same-bar entry (T+1 design)")
    print("  4. Entry research sample size small for pullback/rebreakout — keep collecting")
    return 0


if __name__ == "__main__":
    sys.exit(main())
