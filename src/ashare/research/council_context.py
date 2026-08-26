"""Canonical CouncilContext: Research + Candidate + Live + Reconciliation + DataQuality."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ashare.research.signal_contract import attach_signal_contract, data_quality_from_signals, extract_candidate_signals


COUNCIL_CONTEXT_VERSION = "council_context_v1"


def build_council_context(
    *,
    research: dict[str, Any],
    candidate: dict[str, Any] | None = None,
    live: dict[str, Any] | None = None,
    reconciliation: dict[str, Any] | None = None,
    risk: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Single structured object for prompt serialization.
    Live/reconciliation are advisory only — never mutate research.
    """
    cand = dict(candidate or {})
    if cand:
        attach_signal_contract(cand)
    signals = cand.get("signals") or extract_candidate_signals(cand) if cand else {}
    dq = cand.get("data_quality") or (data_quality_from_signals(signals) if signals else "DEGRADED")
    research_date = str(
        research.get("research_date")
        or research.get("as_of")
        or (research.get("versions") or {}).get("as_of")
        or ""
    )[:10]
    live = dict(live or research.get("live_state") or {})
    recon = dict(reconciliation or research.get("reconciliation") or {})
    return {
        "version": COUNCIL_CONTEXT_VERSION,
        "context_generated_at": datetime.now(timezone.utc).isoformat(),
        "research_date": research_date,
        "live_observed_at": live.get("live_updated_at") or live.get("observed_at"),
        "research": {
            "symbol": research.get("symbol"),
            "research_id": research.get("research_id"),
            "research_date": research_date,
            "quant": research.get("quant"),
            "value_available": research.get("value_available"),
            "market": research.get("market"),
            "as_of": research.get("as_of") or research_date,
        },
        "candidate": {
            "symbol": cand.get("symbol") or research.get("symbol"),
            "candidate_score": cand.get("candidate_score"),
            "signals": signals,
            "data_quality": dq,
            "candidate_sources": cand.get("candidate_sources") or research.get("candidate_sources"),
            "trade_timing_action": cand.get("trade_timing_action") or research.get("trade_timing_action"),
        },
        "live": live,
        "reconciliation": recon,
        "risk": risk or {},
        "data_quality": dq,
    }


def serialize_council_context_for_prompt(ctx: dict[str, Any], *, max_chars: int = 10000) -> dict[str, Any]:
    """Stable prompt payload — do not pull fields from ad-hoc objects."""
    import json

    payload = {
        "version": ctx.get("version"),
        "research_date": ctx.get("research_date"),
        "live_observed_at": ctx.get("live_observed_at"),
        "research": ctx.get("research"),
        "candidate": ctx.get("candidate"),
        "live": ctx.get("live"),
        "reconciliation": ctx.get("reconciliation"),
        "risk": ctx.get("risk"),
        "data_quality": ctx.get("data_quality"),
        "note": "historical_research immutable; live/reconciliation advisory only",
    }
    raw = json.dumps(payload, ensure_ascii=False, default=str)
    if len(raw) <= max_chars:
        return payload
    # Trim news-heavy nests if any
    cand = dict(payload.get("candidate") or {})
    if isinstance(cand.get("signals"), dict):
        cand["signals"] = {
            k: {"value": (v or {}).get("value"), "status": (v or {}).get("status"), "available": (v or {}).get("available")}
            for k, v in (cand.get("signals") or {}).items()
            if isinstance(v, dict)
        }
    payload["candidate"] = cand
    return payload
