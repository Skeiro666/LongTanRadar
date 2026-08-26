"""Cycle-type dispatch for production scheduler.

Does NOT change BUY thresholds / RiskFilter / prompts / scoring.
Maps slots to concrete work units and reports whether full Council runs.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ashare.services.production_cycle import append_live_observation, record_production_run_meta

logger = logging.getLogger("ashare.scheduler.dispatch")

# Explicit: which cycle_types invoke full Research + Council (run_cycle).
FULL_COUNCIL_CYCLE_TYPES = frozenset({"OPENING"})

REASSESSMENT_TRIGGERS = frozenset(
    {
        "BREAK_LIMIT",
        "BREAK_LIMIT_PERSISTED",
        "NEW_EVENT",
        "PRICE_DIVERGENCE",
        "STATE_CHANGE",
        "STATE_RECOVERED",
    }
)


def dispatch_summary() -> dict[str, Any]:
    return {
        "PRE_OPEN": {"full_council": False, "action": "PREPARE"},
        "OPENING": {"full_council": True, "action": "FULL_RESEARCH_COUNCIL"},
        "INTRADAY": {
            "full_council": "conditional",
            "action": "LIVE_OBSERVATION_OR_REASSESSMENT",
            "reassessment_triggers": sorted(REASSESSMENT_TRIGGERS),
        },
        "POST_CLOSE": {"full_council": False, "action": "DAILY_SUMMARY"},
        "note": "Only OPENING always runs full run_cycle. INTRADAY runs it only on reassessment triggers.",
    }


def pending_reassessment_hits(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    try:
        from ashare.services.state_reconciliation import pending_reassessments

        pending = pending_reassessments(cfg)
    except Exception:  # noqa: BLE001
        return []
    hits = []
    for item in pending:
        codes = {str(c).upper() for c in (item.get("trigger_codes") or [])}
        if item.get("trigger"):
            codes.add(str(item.get("trigger")).upper())
        if item.get("primary_trigger"):
            codes.add(str(item.get("primary_trigger")).upper())
        matched = sorted(codes & REASSESSMENT_TRIGGERS)
        if matched:
            hits.append({**item, "matched_triggers": matched})
    return hits


def _focus_rows(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    root = Path(cfg.get("_root") or Path.cwd())
    path = root / "data" / "leader" / "focus_watchlist.json"
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return []
    if isinstance(raw, list):
        return [x for x in raw if isinstance(x, dict)]
    if isinstance(raw, dict):
        items = raw.get("items") or raw.get("focus_watchlist") or raw.get("symbols") or []
        if isinstance(items, list):
            return [x if isinstance(x, dict) else {"symbol": x} for x in items]
    return []


def run_pre_open(cfg: dict[str, Any], *, run_id: str, trading_date: str) -> dict[str, Any]:
    """PRE_OPEN: prepare/preload — no full Council."""
    root = Path(cfg.get("_root") or Path.cwd())
    for rel in (
        "data/reports",
        "data/live_observations",
        "data/cache/scheduler_claims",
        "data/research_snapshots",
    ):
        (root / rel).mkdir(parents=True, exist_ok=True)
    from ashare.calendar.trading_calendar import load_trading_calendar

    cal = load_trading_calendar(cfg)
    d = datetime.fromisoformat(trading_date).date() if "T" not in trading_date else datetime.fromisoformat(trading_date).date()
    out = {
        "run_id": run_id,
        "cycle_type": "PRE_OPEN",
        "action": "PREPARE",
        "full_council": False,
        "full_research": False,
        "trading_date": trading_date,
        "is_trading_day": cal.is_trading_day(d),
        "prepared_at": datetime.now(timezone.utc).isoformat(),
    }
    record_production_run_meta(cfg, {**out, "phase": "pre_open"})
    logger.info("[DISPATCH] PRE_OPEN prepare run_id=%s", run_id)
    return out


def run_live_observation_only(cfg: dict[str, Any], *, run_id: str, trading_date: str) -> dict[str, Any]:
    """INTRADAY without triggers: Live Observation only — no Council."""
    rows = _focus_rows(cfg)
    n = 0
    for row in rows[:80]:
        sym = str(row.get("symbol") or "")
        if not sym:
            continue
        append_live_observation(
            cfg,
            {
                "symbol": sym,
                "as_of": trading_date,
                "research_date": trading_date,
                "price": row.get("live_price") or row.get("close") or row.get("price"),
                "change_pct": row.get("live_change_pct") or row.get("pct_chg"),
                "limit_status": row.get("live_status") or "UNKNOWN",
                "market_state": "INTRADAY",
                "production_run_id": run_id,
                "source": "scheduler_intraday",
            },
        )
        n += 1
    # Optional: refresh advisory for focus names when quotes available (best-effort)
    try:
        if rows:
            from ashare.services.state_reconciliation import refresh_symbols_for_ai

            refresh_symbols_for_ai(rows[:40], cfg=cfg, research_date=trading_date)
    except Exception as exc:  # noqa: BLE001
        logger.debug("live refresh skipped: %s", exc)
    out = {
        "run_id": run_id,
        "cycle_type": "INTRADAY",
        "action": "LIVE_OBSERVATION",
        "full_council": False,
        "full_research": False,
        "live_observation_count": n,
        "reassessment": False,
        "trading_date": trading_date,
    }
    record_production_run_meta(cfg, {**out, "phase": "intraday_live"})
    logger.info("[DISPATCH] INTRADAY live-only obs=%s run_id=%s", n, run_id)
    return out


def run_post_close(cfg: dict[str, Any], *, run_id: str, trading_date: str) -> dict[str, Any]:
    """POST_CLOSE: persist daily summary — no full Council."""
    root = Path(cfg.get("_root") or Path.cwd())
    runs_path = root / "data" / "production_runs.jsonl"
    todays: list[dict[str, Any]] = []
    if runs_path.exists():
        for ln in runs_path.read_text(encoding="utf-8").splitlines():
            if not ln.strip():
                continue
            try:
                row = json.loads(ln)
            except Exception:  # noqa: BLE001
                continue
            if str(row.get("trading_date") or row.get("as_of") or "")[:10] == trading_date:
                todays.append(row)
    summary = {
        "run_id": run_id,
        "cycle_type": "POST_CLOSE",
        "action": "DAILY_SUMMARY",
        "full_council": False,
        "full_research": False,
        "trading_date": trading_date,
        "n_runs_today": len(todays),
        "n_success": sum(1 for r in todays if r.get("success") is True or r.get("status") == "SUCCESS"),
        "n_failed": sum(1 for r in todays if r.get("success") is False or r.get("status") == "FAILED"),
        "n_full_council": sum(1 for r in todays if r.get("full_council") is True),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    out_dir = root / "data" / "daily_summaries"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{trading_date}.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    record_production_run_meta(cfg, {**summary, "phase": "post_close"})
    logger.info("[DISPATCH] POST_CLOSE summary run_id=%s runs=%s", run_id, len(todays))
    return summary


def dispatch_cycle(
    cfg: dict[str, Any],
    *,
    cycle_type: str,
    run_id: str,
    trading_date: str,
    execute: bool = True,
) -> dict[str, Any]:
    """
    Route by cycle_type.

    OPENING → full run_cycle (Research + Council)
    INTRADAY → live only, unless reassessment trigger → full run_cycle
    PRE_OPEN / POST_CLOSE → no full Council
    """
    ctype = str(cycle_type or "").upper()
    if ctype == "CLOSING":
        ctype = "POST_CLOSE"

    if not execute:
        return {
            "dry_run": True,
            "run_id": run_id,
            "cycle_type": ctype,
            "full_council": ctype in FULL_COUNCIL_CYCLE_TYPES,
        }

    if ctype == "PRE_OPEN":
        return run_pre_open(cfg, run_id=run_id, trading_date=trading_date)

    if ctype == "POST_CLOSE":
        return run_post_close(cfg, run_id=run_id, trading_date=trading_date)

    if ctype == "INTRADAY":
        hits = pending_reassessment_hits(cfg)
        if not hits:
            return run_live_observation_only(cfg, run_id=run_id, trading_date=trading_date)
        # Triggered reassessment → full research/council path
        trigger = hits[0].get("matched_triggers") or ["BREAK_LIMIT"]
        cfg = {
            **cfg,
            "_production_run_id": run_id,
            "_cycle_type": "INTRADAY",
            "_reassessment_trigger": trigger[0],
            "_reassessment_hits": hits,
        }
        from ashare.services.agent import run_cycle

        logger.info("[DISPATCH] INTRADAY reassessment triggers=%s run_id=%s", trigger, run_id)
        result = run_cycle(cfg, reset_paper=False)
        if not isinstance(result, dict):
            result = {"result": result}
        result["full_council"] = True
        result["full_research"] = True
        result["reassessment"] = True
        result["reassessment_triggers"] = trigger
        result["cycle_type"] = "INTRADAY"
        result["action"] = "REASSESSMENT"
        return result

    if ctype == "OPENING":
        cfg = {**cfg, "_production_run_id": run_id, "_cycle_type": "OPENING"}
        from ashare.services.agent import run_cycle

        logger.info("[DISPATCH] OPENING full run_cycle run_id=%s", run_id)
        result = run_cycle(cfg, reset_paper=False)
        if not isinstance(result, dict):
            result = {"result": result}
        result["full_council"] = True
        result["full_research"] = True
        result["cycle_type"] = "OPENING"
        result["action"] = "FULL_RESEARCH_COUNCIL"
        return result

    # Unknown — do not guess; mark and skip full council
    logger.warning("[DISPATCH] unknown cycle_type=%s — no-op", ctype)
    return {
        "run_id": run_id,
        "cycle_type": ctype,
        "action": "NOOP_UNKNOWN",
        "full_council": False,
        "full_research": False,
    }
