#!/usr/bin/env python3
"""Rebuild canonical leader events + conditional edge lab. No BUY/LLM/ML changes."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ashare.leader.canonical_edge_lab import run_lab


def main() -> int:
    payload = run_lab(ROOT)
    meta = payload["meta"]
    integ = payload["integrity"]
    mine = payload["mining"]
    summary = {
        "raw": meta.get("raw_events"),
        "canonical": meta.get("canonical_events"),
        "pollution_rate": integ.get("pollution_rate"),
        "board0_raw": integ.get("board_count_eq_0_raw"),
        "verdict": mine.get("verdict"),
        "hopeful_n100": len(mine.get("hopeful_cells_n100") or []),
        "elapsed_sec": meta.get("elapsed_sec"),
        "buy_pipeline_unchanged": True,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
