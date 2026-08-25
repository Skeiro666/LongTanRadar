#!/usr/bin/env python3
"""Fast leader pipeline dry-run: pool → panel → LeaderPipeline only (no news/council LLM)."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ashare.config import load_config
from ashare.data import ensure_panel
from ashare.leader import LeaderPipeline
from ashare.pool.builder import build_leader_pool
from ashare.services.leader_monitor import build_leader_monitor
from ashare.symbols import to_symbol


def main() -> int:
    cfg = load_config()
    cfg["_root"] = str(ROOT)
    pool = build_leader_pool(cfg)
    symbols = [to_symbol(s) for s in (pool.get("symbols") or [])]
    print(f"pool={len(symbols)} sources={pool.get('sources')}", flush=True)
    panel = ensure_panel(cfg, symbols)
    import pandas as pd

    as_of = max(pd.to_datetime(df["date"]).max() for df in panel.values() if not df.empty).date()
    as_of_iso = datetime(as_of.year, as_of.month, as_of.day, 23, 59, 59, tzinfo=timezone.utc).isoformat()

    rows = []
    for c in pool.get("candidates") or []:
        sym = to_symbol(c.get("symbol") or "")
        if sym:
            rows.append({**c, "symbol": sym})

    pipe = LeaderPipeline(cfg)
    pack = pipe.enrich_rows(rows, panel, as_of=as_of_iso)
    enriched = pack["rows"]
    research = enriched[:20]
    uni = {
        "n_union": len(enriched),
        "n_research": len(research),
        "research_universe": research,
        "leader_pipeline": {
            "enabled": True,
            "focus_stats": pack.get("focus_stats"),
            "focus_watchlist": pack.get("focus_watchlist"),
            "leader_rejected": len(pack.get("rejected") or []),
            "dashboard": pipe.dashboard_payload(research),
        },
        "rejected": pack.get("rejected") or [],
    }
    payload = {
        "as_of": str(as_of),
        "candidate_union": uni,
        "platform_reports": [],
        "canonical_decisions": [],
    }
    monitor = build_leader_monitor(cfg, payload)
    out = {
        "as_of": str(as_of),
        "leader_version": str((cfg.get("leader") or {}).get("leader_version") or "leader_v2"),
        "pool_size": len(rows),
        "leader_rejected": len(pack.get("rejected") or []),
        "n_enriched": len(enriched),
        "n_research": len(research),
        "focus_stats": pack.get("focus_stats"),
        "leader_monitor": monitor,
        "stage_counts": {},
        "timing_counts": {},
        "lifecycle_counts": {},
        "reentry_phase_counts": {},
        "top15": [],
    }
    for r in enriched:
        st = str(r.get("stage") or "?")
        ta = str(r.get("trade_timing_action") or "?")
        lc = str(r.get("lifecycle") or "?")
        ph = str(r.get("reentry_phase") or "?")
        out["stage_counts"][st] = out["stage_counts"].get(st, 0) + 1
        out["timing_counts"][ta] = out["timing_counts"].get(ta, 0) + 1
        out["lifecycle_counts"][lc] = out["lifecycle_counts"].get(lc, 0) + 1
        out["reentry_phase_counts"][ph] = out["reentry_phase_counts"].get(ph, 0) + 1
    out["buy_candidate_n"] = out["timing_counts"].get("BUY_CANDIDATE", 0)
    out["buy_ready_n"] = out["timing_counts"].get("BUY_READY", 0)
    out["top15"] = [
        {
            "symbol": r.get("symbol"),
            "name": r.get("name"),
            "board_count": r.get("board_count"),
            "leader_score": r.get("leader_score"),
            "stage": r.get("stage"),
            "chase_score": r.get("chase_score"),
            "chase_level": r.get("chase_level"),
            "reentry_score": r.get("reentry_score"),
            "reentry_phase": r.get("reentry_phase"),
            "trade_timing_score": r.get("trade_timing_score"),
            "trade_timing_action": r.get("trade_timing_action"),
            "lifecycle": r.get("lifecycle"),
            "focus_tier": r.get("focus_tier"),
            "council_tier": r.get("council_tier"),
            "news_tier": r.get("news_tier"),
            "entry_timeline": r.get("entry_timeline"),
            "status_reason": r.get("status_reason"),
        }
        for r in research[:15]
    ]
    path = ROOT / "data" / "leader" / "dry_run_latest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
