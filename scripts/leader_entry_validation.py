#!/usr/bin/env python3
"""Run entry validation (no LLM, frozen params) and write report."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ashare.config import load_config
from ashare.leader.entry_validation import render_markdown_report, run_entry_validation


def main() -> int:
    cfg = load_config()
    cfg["_root"] = str(ROOT)
    report = run_entry_validation(root=ROOT, max_symbols=120, cfg=cfg)
    md = render_markdown_report(report)
    out = ROOT / "docs" / "research" / "ENTRY_VALIDATION_REPORT.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")
    meta = report.get("meta") or {}
    v = report.get("verdicts") or {}
    print(
        {
            "n_samples": meta.get("n_samples"),
            "elapsed_sec": meta.get("elapsed_sec"),
            "llm_calls": meta.get("llm_calls"),
            "tokens": meta.get("tokens"),
            "statistical_edge": v.get("statistical_edge"),
            "calibration": v.get("reentry_calibration_verdict"),
            "extreme_wait_better": v.get("extreme_wait_better_than_chase"),
            "BUY_CANDIDATE": v.get("buy_candidate_count"),
            "BUY_READY": v.get("buy_ready_count"),
            "report": str(out),
            "json": str(ROOT / "data" / "leader" / "entry_validation_latest.json"),
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
