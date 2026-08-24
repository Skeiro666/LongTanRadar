from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ashare.research.token_attribution import summarize_token_attribution


def _load_snapshots(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    root = Path((cfg or {}).get("_root") or Path(__file__).resolve().parents[2])
    d = root / "data" / "research_snapshots"
    if not d.exists():
        return []
    rows: list[dict[str, Any]] = []
    for p in d.glob("R*.json"):
        try:
            rows.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception:  # noqa: BLE001
            continue
    return rows


def build_token_dashboard(cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = cfg or {}
    base = summarize_token_attribution(cfg)
    snaps = _load_snapshots(cfg)
    escalated = 0
    reasons: dict[str, int] = {}
    council_after = 0
    buy_after = 0
    for s in snaps:
        rep = s.get("report") or s
        esc = rep.get("cloud_escalation") or s.get("cloud_escalation") or {}
        if esc.get("escalate"):
            escalated += 1
            r = str(esc.get("escalation_reason") or "unknown")
            for part in r.split("+"):
                if part and part != "none":
                    reasons[part] = reasons.get(part, 0) + 1
            if rep.get("council") or s.get("council"):
                council_after += 1
            rating = str((rep.get("decision") or {}).get("research_rating") or (rep.get("chairman") or {}).get("rating") or "")
            if rating in {"BUY", "STRONG_BUY"}:
                buy_after += 1
    n_snaps = len(snaps)
    rate = round(escalated / n_snaps, 4) if n_snaps else 0.0
    local = base.get("local") or {}
    cloud = base.get("cloud") or {}
    baseline_est = int(local.get("total_tokens") or 0) + int(cloud.get("total_tokens") or 0) + int(base.get("saved_tokens") or 0)
    return {
        **base,
        "cloud_token_saved_pct": base.get("token_saved_pct"),
        "baseline_estimated_tokens": baseline_est,
        "actual_cloud_tokens": cloud.get("total_tokens"),
        "saved_tokens": base.get("saved_tokens"),
        "cloud_escalation": {
            "rate": rate,
            "count": escalated,
            "total_snapshots": n_snaps,
            "reasons": reasons,
            "funnel": {
                "escalated": escalated,
                "entered_council": council_after,
                "final_buy": buy_after,
                "note": "升级样本的 T+10 收益见 Alpha Lab — 需足够样本",
            },
        },
    }
