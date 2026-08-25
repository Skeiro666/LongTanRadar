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
    audit = _load_json(ROOT / "docs" / "research" / "buy_pipeline_audit_raw.json")
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

    print("=== LongTanRadar Leader Pipeline Summary ===")
    print(f"as_of: {as_of}")
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
    print("--- vs Audit baseline (2026-08-24) ---")
    if audit:
        print("  Legacy: 60 pool -> 20 research -> 0 BUY (council WAIT + limit_up risk)")
    print("  New: limit-up hard gate + focus persistence + timing split + tiered council/news")
    print()
    print("--- Remaining risks ---")
    print("  1. research_only=true — canonical BUY unchanged until validation complete")
    print("  2. Council still outputs WAIT_FOR_CONFIRMATION unless prompts/heuristics updated")
    print("  3. T-day limit_up still blocks risk filter for same-bar entries")
    print("  4. Stage/board performance dashboard uses in-cycle samples until counterfactual backtest")
    return 0


if __name__ == "__main__":
    sys.exit(main())
