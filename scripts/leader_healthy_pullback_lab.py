#!/usr/bin/env python3
"""Run Healthy Pullback Lab (0 LLM) and write report."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ashare.config import load_config
from ashare.leader.healthy_pullback_lab import render_healthy_pullback_report, run_healthy_pullback_lab


def main() -> int:
    cfg = load_config()
    cfg["_root"] = str(ROOT)
    report = run_healthy_pullback_lab(root=ROOT, cfg=cfg, max_symbols=250)
    md = render_healthy_pullback_report(report)
    out = ROOT / "docs" / "research" / "HEALTHY_PULLBACK_REPORT.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")
    meta = report.get("meta") or {}
    ans = report.get("answers") or {}
    print(
        {
            "n_pullback_scans": meta.get("n_pullback_scans"),
            "n_healthy": meta.get("n_healthy"),
            "elapsed_sec": meta.get("elapsed_sec"),
            "llm_calls": meta.get("llm_calls"),
            "tokens": meta.get("tokens"),
            "net_ev": ans.get("1_healthy_pullback_net_ev"),
            "prefer_path": (ans.get("5_buy_now_vs_wait_reaccel") or {}).get("prefer"),
            "edge": ans.get("10_statistical_edge"),
            "ready_buy_cand_research": ans.get("9_ready_for_buy_candidate_research"),
            "report": str(out),
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
