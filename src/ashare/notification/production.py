from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ashare.config_loaders import load_yaml_config


def record_production_cycle(
    cfg: dict[str, Any],
    payload: dict[str, Any],
    cycle_id: str | None,
    *,
    notification_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist production validation metrics for V5.3."""
    n_cfg = load_yaml_config(cfg, "notification")
    pv = dict(n_cfg.get("production_validation") or {})
    if not pv.get("enabled", True):
        return {"skipped": True}

    root = Path(cfg.get("_root") or Path(__file__).resolve().parents[3])
    rel = str(pv.get("persist_path") or "data/production_cycles.jsonl")
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)

    canonical = list(payload.get("canonical_decisions") or [])
    buy_n = sum(1 for d in canonical if str(d.get("research_rating") or "").upper() == "BUY")
    sb_n = sum(1 for d in canonical if str(d.get("research_rating") or "").upper() == "STRONG_BUY")
    ai_cost = dict(payload.get("ai_cost") or {})
    budget = dict(ai_cost.get("budget") or {})
    nr = notification_result or {}
    records = list(nr.get("records") or [])

    row = {
        "cycle_id": cycle_id or payload.get("generated_at"),
        "as_of": payload.get("as_of"),
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "candidate_count": (payload.get("candidate_union") or {}).get("n_union"),
        "research_count": (payload.get("candidate_union") or {}).get("n_research"),
        "llm_calls": ai_cost.get("llm_calls") or ai_cost.get("calls"),
        "input_tokens": ai_cost.get("input_tokens"),
        "output_tokens": ai_cost.get("output_tokens"),
        "total_tokens": ai_cost.get("total_tokens"),
        "cost_usd": ai_cost.get("cost_usd"),
        "cache_hit_rate": ai_cost.get("cache_hit_rate"),
        "BUY_count": buy_n,
        "STRONG_BUY_count": sb_n,
        "notification_count": nr.get("sent", 0),
        "notification_failed": nr.get("failed", 0),
        "notification_llm_cost": 0,
        "notification_channel_calls": len(records),
        "paper_fill_count": None,
        "T+5_alpha": _horizon_alpha(payload, "5"),
        "T+10_alpha": _horizon_alpha(payload, "10"),
        "T+20_alpha": _horizon_alpha(payload, "20"),
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    return row


def _horizon_alpha(payload: dict[str, Any], horizon: str) -> float | None:
    pa = (payload.get("research_outcomes") or {}).get("portfolio_attribution") or {}
    if str(pa.get("horizon")) == horizon and pa.get("mean_market_alpha") is not None:
        return pa.get("mean_market_alpha")
    outcomes = (payload.get("research_outcomes") or {}).get("outcomes") or []
    alphas = []
    for o in outcomes:
        cell = (o.get("primary_horizons") or o.get("horizons") or {}).get(horizon) or {}
        if cell.get("market_alpha") is not None:
            alphas.append(float(cell["market_alpha"]))
    if alphas:
        return sum(alphas) / len(alphas)
    return None


def production_summary(cfg: dict[str, Any], limit: int = 30) -> dict[str, Any]:
    n_cfg = load_yaml_config(cfg, "notification")
    rel = str((n_cfg.get("production_validation") or {}).get("persist_path") or "data/production_cycles.jsonl")
    root = Path(cfg.get("_root") or Path(__file__).resolve().parents[3])
    path = root / rel
    if not path.exists():
        return {"available": False, "cycles": []}
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return {"available": True, "cycles": rows[-limit:]}
