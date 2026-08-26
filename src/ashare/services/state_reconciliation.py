"""Deterministic Research ↔ Live State Reconciliation.

Never mutates Research Snapshot fields. Live history is in-memory only.
Advisory bundles feed Roundtable/Council prompts as read-only context.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from ashare.symbols import to_symbol

logger = logging.getLogger("ashare.state_recon")

_TZ = ZoneInfo("Asia/Shanghai")
_LOCK = threading.RLock()

RECON_VERSION = 1

RECON_STATES = ("CONSISTENT", "DEGRADED", "INVALIDATED", "UNKNOWN")
SEVERITIES = ("INFO", "WARNING", "CRITICAL")

# Machine-readable trigger codes (never use Chinese for logic).
TRIGGER_LIVE_LIMIT_UP = "LIVE_LIMIT_UP"
TRIGGER_BREAK_LIMIT = "BREAK_LIMIT"
TRIGGER_BREAK_LIMIT_PERSISTED = "BREAK_LIMIT_PERSISTED"
TRIGGER_REBOUND_TO_LIMIT_UP = "REBOUND_TO_LIMIT_UP"
TRIGGER_PRICE_WEAKENING = "PRICE_WEAKENING"
TRIGGER_LIVE_QUOTE_STALE = "LIVE_QUOTE_STALE"
TRIGGER_LIVE_QUOTE_UNKNOWN = "LIVE_QUOTE_UNKNOWN"
TRIGGER_RESEARCH_LIVE_DIVERGENCE = "RESEARCH_LIVE_DIVERGENCE"
TRIGGER_REASSESSMENT_CANDIDATE = "REASSESSMENT_CANDIDATE"
TRIGGER_ROUND_TABLE_REASSESS_REQUIRED = "ROUND_TABLE_REASSESS_REQUIRED"
TRIGGER_STATE_RECOVERED = "STATE_RECOVERED"

# symbol -> intraday observation cache (not research)
_HISTORY: dict[str, dict[str, Any]] = {}
# symbol -> latest advisory bundle for AI / UI
_ADVISORY: dict[str, dict[str, Any]] = {}
# last logged signature to avoid spam
_LAST_LOG_SIG: dict[str, str] = {}


def _now_cn() -> datetime:
    return datetime.now(_TZ)


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_TZ)
        return dt.astimezone(_TZ)
    except Exception:  # noqa: BLE001
        return None


def live_recon_cfg(cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """Conservative defaults; prefer config/default.yaml data.live.*."""
    cfg = cfg or {}
    data = dict(cfg.get("data") or {})
    live = dict(data.get("live") or {})
    # Also allow leader.live overlay
    try:
        from ashare.config_loaders import load_yaml_config

        lc = load_yaml_config(cfg, "leader")
        for k, v in dict(lc.get("live") or {}).items():
            live.setdefault(k, v)
    except Exception:  # noqa: BLE001
        pass

    stale = int(data.get("live_quote_stale_seconds") or live.get("stale_seconds") or 90)
    return {
        "break_limit_reassess_seconds": int(live.get("break_limit_reassess_seconds") or 300),
        "break_limit_invalidation_seconds": int(live.get("break_limit_invalidation_seconds") or 900),
        "break_limit_rebound_seconds": int(live.get("break_limit_rebound_seconds") or 180),
        "price_divergence_pct": float(live.get("price_divergence_pct") or 3.0),
        "enable_roundtable_reassessment": bool(live.get("enable_roundtable_reassessment", True)),
        "reconciliation_version": int(live.get("reconciliation_version") or RECON_VERSION),
        "stale_seconds": stale,
        "weak_pct": float(live.get("weak_pct") or -3.0),
    }


def build_research_state(row: dict[str, Any]) -> dict[str, Any]:
    """Read-only projection of historical research fields."""
    research_price = row.get("research_price")
    if research_price is None:
        q = row.get("quant") if isinstance(row.get("quant"), dict) else {}
        research_price = row.get("close") or row.get("price") or q.get("close")
    timing = (
        row.get("trade_timing_action")
        or (row.get("chairman") or {}).get("trading_action")
        if isinstance(row.get("chairman"), dict)
        else row.get("trade_timing_action")
    )
    return {
        "research_date": row.get("research_date") or row.get("as_of"),
        "research_price": float(research_price) if research_price is not None else None,
        "board_count": row.get("board_count"),
        "leader_score": row.get("leader_score"),
        "stage": row.get("stage"),
        "reentry_phase": row.get("reentry_phase"),
        "trade_timing_action": timing,
        "research_limit_up": bool(row.get("research_limit_up")),
        "lifecycle": row.get("lifecycle"),
        "focus_tier": row.get("focus_tier"),
    }


def build_live_state(row: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    now = now or _now_cn()
    updated = _parse_iso(row.get("live_updated_at") if isinstance(row.get("live_updated_at"), str) else None)
    age = None
    if updated is not None:
        age = max(0.0, (now - updated).total_seconds())
    elif row.get("live_quote_age_seconds") is not None:
        age = float(row["live_quote_age_seconds"])
    return {
        "live_price": row.get("live_price"),
        "live_change_pct": row.get("live_change_pct"),
        "live_open": row.get("live_open"),
        "live_high": row.get("live_high"),
        "live_low": row.get("live_low"),
        "live_limit_up_price": row.get("live_limit_up_price"),
        "live_limit_down_price": row.get("live_limit_down_price"),
        "live_is_limit_up": bool(row.get("live_is_limit_up")),
        "live_is_limit_down": bool(row.get("live_is_limit_down")),
        "live_status": row.get("live_status") or "UNKNOWN",
        "live_updated_at": row.get("live_updated_at"),
        "live_quote_age_seconds": age,
        "live_session_open": row.get("live_session_open"),
        "break_limit_duration_seconds": row.get("break_limit_duration_seconds"),
    }


def _empty_history(symbol: str) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "first_seen_break_limit_at": None,
        "last_seen_limit_up_at": None,
        "last_seen_break_limit_at": None,
        "consecutive_break_limit_observations": 0,
        "last_live_price": None,
        "last_live_status": None,
        "highest_live_price": None,
        "lowest_live_price": None,
        "saw_break_after_limit_up": False,
        "rebounded_after_break": False,
    }


def update_live_history(
    symbol: str,
    *,
    live_status: str,
    live_price: float | None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Update intraday observation cache. Does not touch research."""
    now = now or _now_cn()
    sym = to_symbol(symbol)
    with _LOCK:
        h = _HISTORY.get(sym) or _empty_history(sym)
        prev_status = h.get("last_live_status")
        status = str(live_status or "UNKNOWN").upper()

        if live_price is not None and float(live_price) > 0:
            px = float(live_price)
            h["last_live_price"] = px
            hi = h.get("highest_live_price")
            lo = h.get("lowest_live_price")
            h["highest_live_price"] = px if hi is None else max(float(hi), px)
            h["lowest_live_price"] = px if lo is None else min(float(lo), px)

        if status == "LIMIT_UP":
            h["last_seen_limit_up_at"] = now
            if prev_status == "BREAK_LIMIT" or h.get("saw_break_after_limit_up"):
                h["rebounded_after_break"] = True
                # Clear break streak after confirmed rebound
                h["first_seen_break_limit_at"] = None
                h["consecutive_break_limit_observations"] = 0
            h["last_live_status"] = status
        elif status == "BREAK_LIMIT":
            if h.get("first_seen_break_limit_at") is None:
                h["first_seen_break_limit_at"] = now
            h["last_seen_break_limit_at"] = now
            h["consecutive_break_limit_observations"] = int(h.get("consecutive_break_limit_observations") or 0) + 1
            if prev_status == "LIMIT_UP" or h.get("last_seen_limit_up_at"):
                h["saw_break_after_limit_up"] = True
            h["rebounded_after_break"] = False
            h["last_live_status"] = status
        else:
            h["last_live_status"] = status

        _HISTORY[sym] = h
        return dict(h)


def break_limit_duration_seconds(history: dict[str, Any], *, now: datetime | None = None) -> float | None:
    now = now or _now_cn()
    start = history.get("first_seen_break_limit_at")
    if start is None:
        return None
    if isinstance(start, str):
        start = _parse_iso(start)
    if not isinstance(start, datetime):
        return None
    if history.get("last_live_status") != "BREAK_LIMIT":
        return None
    return max(0.0, (now - start).total_seconds())


def distance_from_limit_up_pct(live_price: float | None, limit_up: float | None) -> float | None:
    if live_price is None or limit_up is None:
        return None
    px = float(live_price)
    lim = float(limit_up)
    if lim <= 0 or px <= 0:
        return None
    return max(0.0, (lim - px) / lim * 100.0)


def reconcile(
    research: dict[str, Any],
    live: dict[str, Any],
    history: dict[str, Any] | None = None,
    *,
    cfg: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Pure deterministic reconciliation. Never upgrades to BUY."""
    now = now or _now_cn()
    conf = live_recon_cfg(cfg)
    history = history or {}
    live_status = str(live.get("live_status") or "UNKNOWN").upper()
    triggers: list[str] = []
    state = "UNKNOWN"
    severity = "INFO"
    reason = "insufficient_live_or_research"
    triggered = False
    reassessment = "NONE"  # NONE | CANDIDATE | REQUIRED | RECOVERED

    duration = break_limit_duration_seconds(history, now=now)
    if duration is None and live.get("break_limit_duration_seconds") is not None:
        duration = float(live["break_limit_duration_seconds"])
    dist = distance_from_limit_up_pct(live.get("live_price"), live.get("live_limit_up_price"))
    research_lu = bool(research.get("research_limit_up"))
    timing = str(research.get("trade_timing_action") or "").upper()
    strong_research = research_lu or timing in {"BUY_READY", "BUY_CANDIDATE"} or int(research.get("board_count") or 0) >= 2

    if live_status in {"STALE"}:
        triggers.append(TRIGGER_LIVE_QUOTE_STALE)
        return {
            "state": "UNKNOWN",
            "severity": "WARNING",
            "reason": "live_quote_stale_do_not_invalidate_research",
            "triggered": False,
            "trigger_codes": triggers,
            "reassessment": "NONE",
            "break_limit_duration_seconds": duration,
            "distance_from_limit_up_pct": dist,
            "reconciliation_version": conf["reconciliation_version"],
        }
    if live_status in {"UNKNOWN"} or live.get("live_price") in (None, 0):
        triggers.append(TRIGGER_LIVE_QUOTE_UNKNOWN)
        return {
            "state": "UNKNOWN",
            "severity": "INFO",
            "reason": "live_quote_unavailable",
            "triggered": False,
            "trigger_codes": triggers,
            "reassessment": "NONE",
            "break_limit_duration_seconds": duration,
            "distance_from_limit_up_pct": dist,
            "reconciliation_version": conf["reconciliation_version"],
        }

    # Rebound path
    if live_status == "LIMIT_UP" and history.get("rebounded_after_break"):
        triggers.extend([TRIGGER_LIVE_LIMIT_UP, TRIGGER_REBOUND_TO_LIMIT_UP, TRIGGER_STATE_RECOVERED])
        state, severity = "CONSISTENT", "INFO"
        reason = "broke_limit_then_rebounded_to_limit_up"
        reassessment = "RECOVERED"
    elif live_status == "LIMIT_UP":
        triggers.append(TRIGGER_LIVE_LIMIT_UP)
        state, severity = "CONSISTENT", "INFO"
        reason = "live_still_limit_up_vs_research"
        if research_lu or strong_research:
            reason = "research_strength_still_matches_live_limit_up"
    elif live_status == "BREAK_LIMIT":
        triggers.append(TRIGGER_BREAK_LIMIT)
        state, severity = "DEGRADED", "WARNING"
        reason = "live_broke_limit_vs_research_seal"
        reassessment = "CANDIDATE"
        triggers.append(TRIGGER_REASSESSMENT_CANDIDATE)

        reassess_sec = conf["break_limit_reassess_seconds"]
        inval_sec = conf["break_limit_invalidation_seconds"]
        div_pct = conf["price_divergence_pct"]

        if duration is not None and duration >= reassess_sec:
            triggers.append(TRIGGER_BREAK_LIMIT_PERSISTED)
            reason = "break_limit_persisted_without_reseal"
            reassessment = "REQUIRED"
            triggered = True
            triggers.append(TRIGGER_ROUND_TABLE_REASSESS_REQUIRED)

        far = dist is not None and dist >= div_pct
        long_enough = duration is not None and duration >= inval_sec
        if strong_research and far and (long_enough or (duration is not None and duration >= reassess_sec and dist >= div_pct * 1.5)):
            triggers.append(TRIGGER_RESEARCH_LIVE_DIVERGENCE)
            if far:
                triggers.append(TRIGGER_PRICE_WEAKENING)
            state, severity = "INVALIDATED", "CRITICAL"
            reason = "research_assumed_seal_but_live_diverged_from_limit_up"
            reassessment = "REQUIRED"
            triggered = True
            if TRIGGER_ROUND_TABLE_REASSESS_REQUIRED not in triggers:
                triggers.append(TRIGGER_ROUND_TABLE_REASSESS_REQUIRED)
    elif live_status == "WEAK":
        triggers.append(TRIGGER_PRICE_WEAKENING)
        state, severity = "DEGRADED", "WARNING"
        reason = "live_price_weakening"
        if strong_research:
            reassessment = "CANDIDATE"
            triggers.append(TRIGGER_REASSESSMENT_CANDIDATE)
            if dist is not None and dist >= conf["price_divergence_pct"]:
                triggers.append(TRIGGER_RESEARCH_LIVE_DIVERGENCE)
                state, severity = "DEGRADED", "WARNING"
                reassessment = "REQUIRED"
                triggered = True
                triggers.append(TRIGGER_ROUND_TABLE_REASSESS_REQUIRED)
    else:
        # NORMAL
        if research_lu or timing == "BUY_READY":
            triggers.append(TRIGGER_RESEARCH_LIVE_DIVERGENCE)
            state, severity = "DEGRADED", "WARNING"
            reason = "research_expected_strength_but_live_not_limit_up"
            reassessment = "CANDIDATE"
            triggers.append(TRIGGER_REASSESSMENT_CANDIDATE)
        else:
            state, severity = "CONSISTENT", "INFO"
            reason = "live_normal_no_material_divergence"

    # Deduplicate triggers preserving order
    seen: set[str] = set()
    uniq: list[str] = []
    for t in triggers:
        if t not in seen:
            seen.add(t)
            uniq.append(t)

    if not conf["enable_roundtable_reassessment"]:
        triggered = False
        uniq = [t for t in uniq if t != TRIGGER_ROUND_TABLE_REASSESS_REQUIRED]
        if reassessment == "REQUIRED":
            reassessment = "CANDIDATE"

    return {
        "state": state,
        "severity": severity,
        "reason": reason,
        "triggered": triggered,
        "trigger_codes": uniq,
        "reassessment": reassessment,
        "break_limit_duration_seconds": duration,
        "distance_from_limit_up_pct": dist,
        "reconciliation_version": conf["reconciliation_version"],
    }


def _reassessment_path(cfg: dict[str, Any] | None) -> Path:
    root = Path((cfg or {}).get("_root") or ".")
    return root / "data" / "cache" / "live_reassessment.json"


def _load_queue(cfg: dict[str, Any] | None) -> dict[str, Any]:
    path = _reassessment_path(cfg)
    if not path.exists():
        return {"items": {}}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {"items": {}}


def _save_queue(cfg: dict[str, Any] | None, data: dict[str, Any]) -> None:
    path = _reassessment_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def enqueue_reassessment(
    *,
    symbol: str,
    research_date: str | None,
    trigger_codes: list[str],
    reconciliation: dict[str, Any],
    cfg: dict[str, Any] | None = None,
) -> str | None:
    """Idempotent queue: symbol + research_date + primary trigger. Does not call LLM."""
    if TRIGGER_ROUND_TABLE_REASSESS_REQUIRED not in trigger_codes:
        return None
    conf = live_recon_cfg(cfg)
    if not conf["enable_roundtable_reassessment"]:
        return None
    sym = to_symbol(symbol)
    primary = TRIGGER_BREAK_LIMIT_PERSISTED
    if TRIGGER_RESEARCH_LIVE_DIVERGENCE in trigger_codes:
        primary = TRIGGER_RESEARCH_LIVE_DIVERGENCE
    key = f"{sym}|{research_date or ''}|{primary}"
    with _LOCK:
        data = _load_queue(cfg)
        items = data.setdefault("items", {})
        existing = items.get(key)
        if existing and existing.get("status") in {"pending", "in_progress"}:
            return key
        items[key] = {
            "key": key,
            "symbol": sym,
            "research_date": research_date,
            "trigger_codes": list(trigger_codes),
            "primary_trigger": primary,
            "reconciliation_state": reconciliation.get("state"),
            "severity": reconciliation.get("severity"),
            "reason": reconciliation.get("reason"),
            "status": "pending",
            "enqueued_at": _now_cn().isoformat(timespec="seconds"),
        }
        _save_queue(cfg, data)
        logger.info(
            "[ROUND_TABLE_REASSESSMENT] symbol=%s trigger=%s research_date=%s",
            sym,
            primary,
            research_date,
        )
        return key


def pending_reassessments(cfg: dict[str, Any] | None = None, *, symbol: str | None = None) -> list[dict[str, Any]]:
    data = _load_queue(cfg)
    out = []
    for item in (data.get("items") or {}).values():
        if item.get("status") != "pending":
            continue
        if symbol and to_symbol(symbol) != to_symbol(str(item.get("symbol") or "")):
            continue
        out.append(item)
    return out


def mark_reassessment_consumed(key: str, cfg: dict[str, Any] | None = None) -> None:
    with _LOCK:
        data = _load_queue(cfg)
        items = data.get("items") or {}
        if key in items:
            items[key]["status"] = "consumed"
            items[key]["consumed_at"] = _now_cn().isoformat(timespec="seconds")
            _save_queue(cfg, data)


def has_pending_live_divergence(symbol: str, cfg: dict[str, Any] | None = None) -> bool:
    return bool(pending_reassessments(cfg, symbol=symbol))


def build_context_meta(
    research: dict[str, Any],
    live: dict[str, Any],
    *,
    cfg: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or _now_cn()
    conf = live_recon_cfg(cfg)
    return {
        "context_generated_at": now.isoformat(timespec="seconds"),
        "research_date": research.get("research_date"),
        "live_observed_at": live.get("live_updated_at"),
        "reconciliation_version": conf["reconciliation_version"],
    }


def build_market_state_bundle(
    row: dict[str, Any],
    *,
    cfg: dict[str, Any] | None = None,
    now: datetime | None = None,
    update_history: bool = True,
) -> dict[str, Any]:
    """Build Research + Live + Reconciliation bundle; update caches; never mutate research inputs."""
    now = now or _now_cn()
    sym = to_symbol(str(row.get("symbol") or ""))
    research = build_research_state(row)
    # Ensure research_limit_up from overlay inference if missing
    if not research.get("research_limit_up"):
        from ashare.services.live_quote_overlay import research_was_limit_up

        research["research_limit_up"] = research_was_limit_up(row)

    live_status = str(row.get("live_status") or "UNKNOWN")
    live_price = row.get("live_price")
    hist = None
    if update_history and sym:
        hist = update_live_history(sym, live_status=live_status, live_price=live_price, now=now)
    else:
        hist = dict(_HISTORY.get(sym) or _empty_history(sym))

    duration = break_limit_duration_seconds(hist, now=now)
    live = build_live_state(row, now=now)
    live["break_limit_duration_seconds"] = duration
    if hist.get("highest_live_price") is not None:
        live["live_high_session"] = hist["highest_live_price"]
    if hist.get("lowest_live_price") is not None:
        live["live_low_session"] = hist["lowest_live_price"]

    recon = reconcile(research, live, hist, cfg=cfg, now=now)
    meta = build_context_meta(research, live, cfg=cfg, now=now)

    # Append-only LiveObservation — never mutates Research Snapshot
    observation_id = None
    try:
        from ashare.services.production_cycle import append_live_observation

        obs_path = append_live_observation(
            cfg or {},
            {
                "symbol": sym,
                "observed_at": (live.get("observed_at") or now.isoformat()),
                "price": live.get("live_price") or row.get("live_price") or row.get("close"),
                "change_pct": live.get("live_change_pct") or row.get("live_change_pct") or row.get("pct_chg"),
                "limit_status": live.get("live_status") or live_status,
                "volume": row.get("volume") or row.get("vol"),
                "turnover": row.get("amount") or row.get("turnover"),
                "market_state": recon.get("state"),
                "research_date": research.get("research_date"),
                "as_of": research.get("research_date"),
                "research_snapshot_id": row.get("research_id") or row.get("snapshot_id"),
                "production_run_id": (cfg or {}).get("_production_run_id"),
            },
        )
        # observation_id is written inside append; re-read last line id if needed
        observation_id = f"L{sym}-{now.strftime('%H%M%S')}"
        live["observation_id"] = observation_id
    except Exception:  # noqa: BLE001
        pass

    recon["research_snapshot_id"] = row.get("research_id") or row.get("snapshot_id")
    recon["live_observation_id"] = live.get("observation_id") or observation_id
    recon["production_run_id"] = (cfg or {}).get("_production_run_id")

    if recon.get("triggered"):
        enqueue_reassessment(
            symbol=sym,
            research_date=str(research.get("research_date") or ""),
            trigger_codes=list(recon.get("trigger_codes") or []),
            reconciliation=recon,
            cfg=cfg,
        )

    bundle = {
        "symbol": sym,
        "research_state": research,
        "live_state": live,
        "reconciliation": recon,
        "context": meta,
        "history_summary": {
            "consecutive_break_limit_observations": hist.get("consecutive_break_limit_observations"),
            "saw_break_after_limit_up": hist.get("saw_break_after_limit_up"),
            "rebounded_after_break": hist.get("rebounded_after_break"),
            "highest_live_price": hist.get("highest_live_price"),
            "lowest_live_price": hist.get("lowest_live_price"),
        },
    }

    with _LOCK:
        _ADVISORY[sym] = bundle
        sig = f"{recon.get('state')}|{recon.get('severity')}|{','.join(recon.get('trigger_codes') or [])}"
        if _LAST_LOG_SIG.get(sym) != sig:
            _LAST_LOG_SIG[sym] = sig
            logger.info(
                "[STATE_RECONCILIATION] symbol=%s research_date=%s research_state=%s "
                "live_status=%s reconciliation=%s severity=%s trigger=%s",
                sym,
                research.get("research_date"),
                research.get("trade_timing_action") or research.get("stage"),
                live.get("live_status"),
                recon.get("state"),
                recon.get("severity"),
                ",".join(recon.get("trigger_codes") or []) or "-",
            )
    return bundle


def get_advisory(symbol: str) -> dict[str, Any] | None:
    sym = to_symbol(symbol)
    with _LOCK:
        b = _ADVISORY.get(sym)
        return dict(b) if b else None


def advisory_for_prompt(symbol: str | None = None, row: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Slim advisory block for LLM prompts (read-only)."""
    if row and (row.get("market_state_bundle") or row.get("reconciliation")):
        bundle = row.get("market_state_bundle") or {
            "research_state": row.get("research_state"),
            "live_state": {
                k: row.get(k)
                for k in (
                    "live_price",
                    "live_change_pct",
                    "live_status",
                    "live_updated_at",
                    "live_limit_up_price",
                    "break_limit_duration_seconds",
                )
            },
            "reconciliation": row.get("reconciliation"),
            "context": row.get("market_state_context"),
        }
    elif symbol:
        bundle = get_advisory(symbol)
    else:
        return None
    if not bundle:
        return None
    research = bundle.get("research_state") or {}
    live = bundle.get("live_state") or {}
    recon = bundle.get("reconciliation") or {}
    return {
        "layer_semantics": {
            "historical_research": "immutable research facts as-of research_date; not live",
            "live_market_state": "intraday observation only; not a completed daily bar",
            "reconciliation": "deterministic system judgment of research vs live; not a trade signal",
        },
        "rules": [
            "Do not rewrite historical research fields from live prices.",
            "Do not treat live price as completed daily close/board_count.",
            "If research conflicts with live, acknowledge live has changed.",
            "BREAK_LIMIT is not automatic leader invalidation; use duration/distance/reseal.",
            "If reconciliation.state=INVALIDATED, do not mechanically keep prior BUY_READY.",
            "Allowed opinions: WAIT / DOWNGRADE / REASSESS / PASS / KEEP_WATCHING.",
            "Live/reconciliation must not bypass RiskFilter or BUY gates; never BUY from live alone.",
        ],
        "historical_research": research,
        "live_market_state": live,
        "state_reconciliation": recon,
        "context": bundle.get("context") or {},
        "history_summary": bundle.get("history_summary") or {},
    }


def attach_reconciliation_overlay(
    rows: list[dict[str, Any]],
    *,
    cfg: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Attach reconciliation_* / nested bundles onto monitor rows (overlay keys only)."""
    now = _now_cn()
    for row in rows:
        if not row.get("symbol"):
            continue
        # Freeze research fields before any overlay write
        frozen = {
            "board_count": row.get("board_count"),
            "leader_score": row.get("leader_score"),
            "stage": row.get("stage"),
            "research_date": row.get("research_date"),
            "research_limit_up": row.get("research_limit_up"),
        }
        bundle = build_market_state_bundle(row, cfg=cfg, now=now, update_history=True)
        recon = bundle["reconciliation"]
        row["research_state"] = bundle["research_state"]
        row["live_state"] = bundle["live_state"]
        row["reconciliation"] = recon
        row["reconciliation_state"] = recon.get("state")
        row["reconciliation_severity"] = recon.get("severity")
        row["reconciliation_reason"] = recon.get("reason")
        row["reconciliation_triggers"] = list(recon.get("trigger_codes") or [])
        row["reassessment"] = recon.get("reassessment")
        row["break_limit_duration_seconds"] = recon.get("break_limit_duration_seconds")
        row["market_state_context"] = bundle.get("context")
        row["market_state_bundle"] = bundle
        # Restore frozen research fields (defense in depth)
        for k, v in frozen.items():
            if v is not None or k in row:
                row[k] = frozen[k]
    return rows


def refresh_symbols_for_ai(
    rows: list[dict[str, Any]],
    *,
    cfg: dict[str, Any] | None = None,
    research_date: str | None = None,
) -> list[dict[str, Any]]:
    """Fetch live quotes + reconcile for AI context. Does not persist into research snapshots."""
    from ashare.services.live_quote_overlay import attach_live_quote_overlay

    attach_live_quote_overlay(rows, cfg=cfg, research_date=research_date, fetch=True)
    attach_reconciliation_overlay(rows, cfg=cfg)
    return rows


def reset_reconciliation_state() -> None:
    """Test helper."""
    global _HISTORY, _ADVISORY, _LAST_LOG_SIG
    with _LOCK:
        _HISTORY = {}
        _ADVISORY = {}
        _LAST_LOG_SIG = {}
