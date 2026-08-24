from __future__ import annotations

import json
from pathlib import Path
from typing import Any

LOCAL_CALL_SITES = frozenset({"news_intelligence", "news_llm_mapping", "news_entity"})
CLOUD_ROLES = frozenset({"fundamental", "quant", "event", "valuation", "bear", "chair", "dragon", "risk"})


def _load_usage(root: Path) -> list[dict[str, Any]]:
    path = root / "data" / "ai" / "usage.jsonl"
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    try:
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return []
    return rows


def summarize_token_attribution(cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    root = Path((cfg or {}).get("_root") or Path(__file__).resolve().parents[3])
    rows = _load_usage(root)

    local = {"calls": 0, "cache_hits": 0, "input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "latency_ms": 0.0}
    cloud = {"calls": 0, "input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "cost_usd": 0.0}
    saved_tokens = 0

    for r in rows:
        site = str(r.get("call_site") or "")
        role = str(r.get("role") or "")
        cache_hit = bool(r.get("cache_hit"))
        inp = int(r.get("input_tokens") or 0)
        out = int(r.get("output_tokens") or 0)
        tot = int(r.get("total_tokens") or inp + out)

        if site in LOCAL_CALL_SITES or role in {"news_intel", "news_entity"}:
            if cache_hit:
                local["cache_hits"] += 1
                saved_tokens += int(r.get("cache_saved_tokens") or tot)
            else:
                local["calls"] += 1
            local["input_tokens"] += inp
            local["output_tokens"] += out
            local["total_tokens"] += tot
            local["latency_ms"] += float(r.get("latency_ms") or 0)
        elif role in CLOUD_ROLES or site.startswith("council") or site in {"chairman", "roundtable", "ai_select"}:
            if not cache_hit:
                cloud["calls"] += 1
            cloud["input_tokens"] += inp
            cloud["output_tokens"] += out
            cloud["total_tokens"] += tot
            cloud["cost_usd"] += float(r.get("estimated_cost_usd") or 0)

    baseline = local["total_tokens"] + cloud["total_tokens"] + saved_tokens
    saved_pct = round(saved_tokens / baseline * 100, 2) if baseline > 0 else 0.0

    return {
        "local": local,
        "cloud": cloud,
        "saved_tokens": saved_tokens,
        "token_saved_pct": saved_pct,
        "available": bool(rows),
    }
