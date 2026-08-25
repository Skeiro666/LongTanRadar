#!/usr/bin/env python3
"""Run entry distribution lab (0 LLM) and write markdown report."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ashare.config import load_config
from ashare.leader.entry_distribution import render_distribution_report, run_distribution_lab


def main() -> int:
    cfg = load_config()
    cfg["_root"] = str(ROOT)
    report = run_distribution_lab(root=ROOT, cfg=cfg, max_symbols=120)
    md = render_distribution_report(report)
    out = ROOT / "docs" / "research" / "ENTRY_DISTRIBUTION_REPORT.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")
    meta = report.get("meta") or {}
    ans = report.get("answers") or {}
    print(
        {
            "n_samples": meta.get("n_samples"),
            "elapsed_sec": meta.get("elapsed_sec"),
            "llm_calls": meta.get("llm_calls"),
            "tokens": meta.get("tokens"),
            "cost_rate": meta.get("cost_rate_round_trip"),
            "overall": ans.get("overall"),
            "risk_adj_edge": ans.get("8_risk_adjusted_entry_edge"),
            "best_board_entry": ans.get("6_best_board_entry"),
            "report": str(out),
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
