"""Trading-day production scheduler — independent of agent.autostart.

States: STOPPED | STARTING | RUNNING | PAUSED | MARKET_CLOSED | ERROR
Slot statuses: SCHEDULED | CLAIMED | RUNNING | SUCCESS | FAILED | MISSED
Cycle types: PRE_OPEN | OPENING | INTRADAY | POST_CLOSE

Does not change BUY thresholds.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import date, datetime, time as dtime
from typing import Any
from zoneinfo import ZoneInfo

from ashare.calendar.trading_calendar import load_trading_calendar
from ashare.services.production_cycle import (
    STATUS_FAILED,
    STATUS_MISSED,
    STATUS_RUNNING,
    STATUS_SCHEDULED,
    STATUS_SUCCESS,
    AtomicIdempotencyStore,
    idempotency_key,
    new_run_id,
    record_production_run_meta,
)
from ashare.services.scheduler_dispatch import dispatch_cycle, dispatch_summary

logger = logging.getLogger("ashare.scheduler")

STATE_STOPPED = "STOPPED"
STATE_STARTING = "STARTING"
STATE_RUNNING = "RUNNING"
STATE_PAUSED = "PAUSED"
STATE_MARKET_CLOSED = "MARKET_CLOSED"
STATE_ERROR = "ERROR"

SLOT_PRE_OPEN = "PRE_OPEN"
SLOT_OPENING = "OPENING"
SLOT_INTRADAY = "INTRADAY"
SLOT_POST_CLOSE = "POST_CLOSE"
SLOT_CLOSING = SLOT_POST_CLOSE

_lock = threading.RLock()
_thread: threading.Thread | None = None
_stop = threading.Event()
_health: dict[str, Any] = {
    "scheduler_state": STATE_STOPPED,
    "enabled": False,
    "last_run_id": None,
    "last_success_at": None,
    "last_failure_at": None,
    "last_cycle_duration_sec": None,
    "last_cycle_type": None,
    "last_error": "",
    "last_candidate_count": None,
    "last_research_count": None,
    "last_council_count": None,
    "last_buy_count": None,
    "today_runs": 0,
    "today_success": 0,
    "today_failed": 0,
    "today_missed": 0,
    "today_date": None,
    "missed_runs": [],
    "today_slots": [],
    "dispatch": dispatch_summary(),
}


def scheduler_cfg(cfg: dict[str, Any]) -> dict[str, Any]:
    base = dict(cfg.get("scheduler") or {})
    return {
        "enabled": bool(base.get("enabled", True)),
        "timezone": str(base.get("timezone") or "Asia/Shanghai"),
        "market": str(base.get("market") or "SSE"),
        "run_on_trading_days": bool(base.get("run_on_trading_days", True)),
        "poll_sec": float(base.get("poll_sec") or 20),
        "max_late_seconds": float(base.get("max_late_seconds") or 900),
        "claim_lease_sec": int(base.get("claim_lease_sec") or 3600),
        "pre_open": str(base.get("pre_open") or "09:15"),
        "opening": str(base.get("opening") or "09:35"),
        "intraday": list(base.get("intraday") or ["10:30", "11:00", "14:00"]),
        "closing": str(base.get("closing") or base.get("post_close") or "15:05"),
        "execute_cycles": bool(base.get("execute_cycles", True)),
    }


def health_snapshot() -> dict[str, Any]:
    with _lock:
        out = dict(_health)
        out["today_slots"] = list(_health.get("today_slots") or [])
        out["dispatch"] = dispatch_summary()
        return out


def _set_health(**kwargs: Any) -> None:
    with _lock:
        _health.update(kwargs)


def _parse_hhmm(s: str) -> dtime:
    parts = str(s).strip().split(":")
    return dtime(int(parts[0]), int(parts[1]) if len(parts) > 1 else 0)


def _local_now(tz: ZoneInfo) -> datetime:
    return datetime.now(tz)


def planned_slots(cfg: dict[str, Any], trading_day: date) -> list[dict[str, Any]]:
    sc = scheduler_cfg(cfg)
    tz = ZoneInfo(sc["timezone"])
    rows: list[dict[str, Any]] = [
        {"cycle_type": SLOT_PRE_OPEN, "slot": SLOT_PRE_OPEN,
         "scheduled_at": datetime.combine(trading_day, _parse_hhmm(sc["pre_open"]), tzinfo=tz)},
        {"cycle_type": SLOT_OPENING, "slot": SLOT_OPENING,
         "scheduled_at": datetime.combine(trading_day, _parse_hhmm(sc["opening"]), tzinfo=tz)},
    ]
    for i, hhmm in enumerate(sc["intraday"]):
        rows.append({
            "cycle_type": SLOT_INTRADAY,
            "slot": f"{SLOT_INTRADAY}_{i}_{hhmm}",
            "scheduled_at": datetime.combine(trading_day, _parse_hhmm(hhmm), tzinfo=tz),
        })
    rows.append({
        "cycle_type": SLOT_POST_CLOSE,
        "slot": SLOT_POST_CLOSE,
        "scheduled_at": datetime.combine(trading_day, _parse_hhmm(sc["closing"]), tzinfo=tz),
    })
    return rows


def _due_or_missed(cfg: dict[str, Any], now: datetime, cal) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    sc = scheduler_cfg(cfg)
    today = now.date()
    if sc["run_on_trading_days"] and not cal.is_trading_day(today):
        return [], []
    max_late = float(sc["max_late_seconds"])
    store = AtomicIdempotencyStore(cfg, lease_sec=int(sc["claim_lease_sec"]))
    due: list[dict[str, Any]] = []
    missed: list[dict[str, Any]] = []
    for plan in planned_slots(cfg, today):
        target: datetime = plan["scheduled_at"]
        if now < target:
            continue
        late = (now - target).total_seconds()
        key = idempotency_key(today.isoformat(), plan["cycle_type"], plan["slot"])
        rec = store.get(key)
        if rec:
            st = str(rec.get("status") or "")
            if st in {STATUS_SUCCESS, STATUS_FAILED, STATUS_MISSED}:
                continue
            if st in {STATUS_RUNNING, "CLAIMED"} and not store._is_reclaimable(rec):
                continue
        entry = {**plan, "idempotency_key": key, "late_seconds": late, "scheduled_at_iso": target.isoformat()}
        if late <= max_late:
            due.append(entry)
        else:
            missed.append(entry)
    due.sort(key=lambda x: x["scheduled_at"])
    missed.sort(key=lambda x: x["scheduled_at"])
    return due, missed


def _reset_today_counters(today: str) -> None:
    with _lock:
        if _health.get("today_date") != today:
            _health["today_date"] = today
            _health["today_runs"] = 0
            _health["today_success"] = 0
            _health["today_failed"] = 0
            _health["today_missed"] = 0
            _health["today_slots"] = []
            _health["missed_runs"] = []


def _upsert_today_slot(row: dict[str, Any]) -> None:
    with _lock:
        slots = list(_health.get("today_slots") or [])
        key = row.get("slot")
        found = False
        for i, s in enumerate(slots):
            if s.get("slot") == key:
                slots[i] = {**s, **row}
                found = True
                break
        if not found:
            slots.append(row)
        slots.sort(key=lambda x: str(x.get("scheduled_at") or ""))
        _health["today_slots"] = slots


def _sync_today_slots_view(cfg: dict[str, Any], now: datetime) -> None:
    sc = scheduler_cfg(cfg)
    today = now.date()
    store = AtomicIdempotencyStore(cfg, lease_sec=int(sc["claim_lease_sec"]))
    rows = []
    for plan in planned_slots(cfg, today):
        key = idempotency_key(today.isoformat(), plan["cycle_type"], plan["slot"])
        rec = store.get(key) or {}
        status = str(rec.get("status") or STATUS_SCHEDULED)
        rows.append({
            "slot": plan["slot"],
            "cycle_type": plan["cycle_type"],
            "scheduled_at": plan["scheduled_at"].isoformat(),
            "status": status,
            "run_id": rec.get("run_id"),
            "started_at": rec.get("started_at") or rec.get("claimed_at"),
            "finished_at": rec.get("finished_at"),
            "error": rec.get("error"),
        })
    with _lock:
        _health["today_date"] = today.isoformat()
        _health["today_slots"] = rows


def _execute_slot(
    cfg: dict[str, Any],
    *,
    trading_date: str,
    cycle_type: str,
    slot: str,
    scheduled_at: str | None = None,
) -> dict[str, Any]:
    from ashare.config import load_config

    if cycle_type == "CLOSING":
        cycle_type = SLOT_POST_CLOSE
    if slot == "CLOSING":
        slot = SLOT_POST_CLOSE

    cfg = load_config(cfg.get("_config_path")) if cfg.get("_config_path") else cfg
    sc = scheduler_cfg(cfg)
    key = idempotency_key(trading_date, cycle_type, slot)
    store = AtomicIdempotencyStore(cfg, lease_sec=int(sc["claim_lease_sec"]))
    run_id = new_run_id()

    claim = store.claim_once(
        key,
        run_id=run_id,
        meta={
            "cycle_type": cycle_type,
            "scheduled_slot": slot,
            "slot": slot,
            "trading_date": trading_date,
            "scheduled_at": scheduled_at,
        },
    )
    if not claim.claimed:
        logger.info("[SCHEDULER] skip idempotent key=%s run_id=%s status=%s", key, claim.run_id, claim.status)
        _upsert_today_slot({
            "slot": slot, "cycle_type": cycle_type, "scheduled_at": scheduled_at,
            "status": claim.status, "run_id": claim.run_id,
            "started_at": (claim.record or {}).get("started_at"),
            "finished_at": (claim.record or {}).get("finished_at"),
            "error": (claim.record or {}).get("error"),
        })
        return {
            "skipped": True, "reason": "IDEMPOTENT", "run_id": claim.run_id,
            "idempotency_key": key, "status": claim.status,
        }

    _reset_today_counters(trading_date)
    with _lock:
        _health["today_runs"] = int(_health.get("today_runs") or 0) + 1
        _health["last_run_id"] = run_id
        _health["last_cycle_type"] = cycle_type
    store.update_status(key, status=STATUS_RUNNING)
    started_at = datetime.now().astimezone().isoformat()
    _upsert_today_slot({
        "slot": slot, "cycle_type": cycle_type, "scheduled_at": scheduled_at,
        "status": STATUS_RUNNING, "run_id": run_id, "started_at": started_at,
        "finished_at": None, "error": None,
    })

    t0 = time.time()
    ok = False
    err = ""
    result: dict[str, Any] = {}
    try:
        cfg = {**cfg, "_production_run_id": run_id, "_cycle_type": cycle_type, "_scheduled_slot": slot}
        logger.info("[SCHEDULER] fire trading_date=%s cycle_type=%s slot=%s run_id=%s",
                    trading_date, cycle_type, slot, run_id)
        result = dispatch_cycle(
            cfg, cycle_type=cycle_type, run_id=run_id, trading_date=trading_date,
            execute=bool(sc.get("execute_cycles", True)),
        )
        ok = True
    except Exception as exc:  # noqa: BLE001
        err = str(exc)[:300]
        logger.exception("[SCHEDULER] cycle failed: %s", exc)
        ok = False

    dur = round(time.time() - t0, 3)
    picks = result.get("picks") if isinstance(result.get("picks"), dict) else result
    if not isinstance(picks, dict):
        picks = {}
    research = picks if "platform_reports" in picks else (result.get("research") or picks)
    if not isinstance(research, dict):
        research = {}
    finished_at = datetime.now().astimezone().isoformat()
    status = STATUS_SUCCESS if ok else STATUS_FAILED
    store.update_status(key, status=status, error=err or None,
                        extra={"duration_sec": dur, "full_council": bool(result.get("full_council"))})
    meta = {
        "run_id": run_id, "trading_date": trading_date, "cycle_type": cycle_type,
        "scheduled_slot": slot, "scheduled_at": scheduled_at, "idempotency_key": key,
        "success": ok, "status": status, "error": err or None, "duration_sec": dur,
        "full_council": bool(result.get("full_council")),
        "full_research": bool(result.get("full_research") or result.get("full_council")),
        "action": result.get("action"), "reassessment": bool(result.get("reassessment")),
        "candidate_count": (research.get("candidate_union") or {}).get("n_union")
            or research.get("candidate_count") or result.get("live_observation_count"),
        "research_count": (research.get("candidate_union") or {}).get("n_research")
            or research.get("research_count"),
        "council_count": len(research.get("platform_reports") or []) if result.get("full_council") else 0,
        "buy_count": sum(1 for d in (research.get("canonical_decisions") or []) if d.get("committee_approve"))
            if result.get("full_council") else 0,
        "recorded_at": finished_at,
    }
    try:
        record_production_run_meta(cfg, meta)
    except Exception:  # noqa: BLE001
        pass
    _upsert_today_slot({
        "slot": slot, "cycle_type": cycle_type, "scheduled_at": scheduled_at,
        "status": status, "run_id": run_id, "started_at": started_at,
        "finished_at": finished_at, "error": err or None,
    })
    if ok:
        with _lock:
            _health["today_success"] = int(_health.get("today_success") or 0) + 1
            _health["last_success_at"] = finished_at
            _health["last_cycle_duration_sec"] = dur
            _health["last_candidate_count"] = meta.get("candidate_count")
            _health["last_research_count"] = meta.get("research_count")
            _health["last_council_count"] = meta.get("council_count")
            _health["last_buy_count"] = meta.get("buy_count")
            _health["last_error"] = ""
            _health["scheduler_state"] = STATE_RUNNING
    else:
        with _lock:
            _health["today_failed"] = int(_health.get("today_failed") or 0) + 1
            _health["last_failure_at"] = finished_at
            _health["last_error"] = err
            _health["scheduler_state"] = STATE_ERROR
    return meta


def _mark_missed_slots(cfg: dict[str, Any], missed: list[dict[str, Any]]) -> None:
    sc = scheduler_cfg(cfg)
    store = AtomicIdempotencyStore(cfg, lease_sec=int(sc["claim_lease_sec"]))
    for m in missed:
        key = m["idempotency_key"]
        td = m["scheduled_at"].date().isoformat() if hasattr(m["scheduled_at"], "date") else str(m.get("scheduled_at"))[:10]
        claim = store.mark_missed(key, meta={
            "cycle_type": m["cycle_type"], "scheduled_slot": m["slot"], "slot": m["slot"],
            "trading_date": td, "scheduled_at": m.get("scheduled_at_iso"),
            "late_seconds": m.get("late_seconds"), "reason": "MARK_MISSED",
        })
        if claim.reason == "MARK_MISSED" or claim.status == STATUS_MISSED:
            with _lock:
                _health["today_missed"] = int(_health.get("today_missed") or 0) + 1
                recent = list(_health.get("missed_runs") or [])
                row = {
                    "date": td, "expected_start": m.get("scheduled_at_iso"), "actual_start": None,
                    "reason": "MISSED_RUN", "slot": m["slot"], "cycle_type": m["cycle_type"],
                    "late_seconds": m.get("late_seconds"),
                }
                if not any(x.get("slot") == row["slot"] and x.get("date") == row["date"] for x in recent):
                    recent.append(row)
                    _health["missed_runs"] = recent[-50:]
            _upsert_today_slot({
                "slot": m["slot"], "cycle_type": m["cycle_type"], "scheduled_at": m.get("scheduled_at_iso"),
                "status": STATUS_MISSED, "run_id": claim.run_id, "started_at": None,
                "finished_at": datetime.now().astimezone().isoformat(), "error": "MARK_MISSED",
            })
            logger.warning("[SCHEDULER] MARK_MISSED %s late=%s", m["slot"], m.get("late_seconds"))


def _loop(cfg: dict[str, Any]) -> None:
    sc = scheduler_cfg(cfg)
    tz = ZoneInfo(sc["timezone"])
    poll = float(sc["poll_sec"])
    _set_health(scheduler_state=STATE_RUNNING, enabled=True, dispatch=dispatch_summary())
    logger.info("[SCHEDULER] started tz=%s poll_sec=%s max_late_seconds=%s",
                sc["timezone"], poll, sc["max_late_seconds"])
    while not _stop.is_set():
        try:
            cfg_live = cfg
            try:
                from ashare.config import load_config
                cfg_live = load_config()
                cfg_live["_root"] = cfg.get("_root") or cfg_live.get("_root")
            except Exception:  # noqa: BLE001
                pass
            sc = scheduler_cfg(cfg_live)
            cal = load_trading_calendar(cfg_live)
            now = _local_now(tz)
            today = now.date()
            _reset_today_counters(today.isoformat())
            if sc["run_on_trading_days"] and not cal.is_trading_day(today):
                _set_health(scheduler_state=STATE_MARKET_CLOSED)
                _sync_today_slots_view(cfg_live, now)
            else:
                if _health.get("scheduler_state") == STATE_MARKET_CLOSED:
                    _set_health(scheduler_state=STATE_RUNNING)
                due, missed = _due_or_missed(cfg_live, now, cal)
                if missed:
                    _mark_missed_slots(cfg_live, missed)
                for item in due:
                    _execute_slot(
                        cfg_live, trading_date=today.isoformat(),
                        cycle_type=item["cycle_type"], slot=item["slot"],
                        scheduled_at=item.get("scheduled_at_iso"),
                    )
                _sync_today_slots_view(cfg_live, now)
        except Exception as exc:  # noqa: BLE001
            logger.exception("[SCHEDULER] loop error: %s", exc)
            _set_health(scheduler_state=STATE_ERROR, last_error=str(exc)[:200])
        _stop.wait(poll)
    _set_health(scheduler_state=STATE_STOPPED)
    logger.info("[SCHEDULER] stopped")


def start_scheduler(cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    global _thread
    from ashare.config import load_config
    cfg = cfg or load_config()
    sc = scheduler_cfg(cfg)
    if not sc["enabled"]:
        _set_health(scheduler_state=STATE_STOPPED, enabled=False)
        return {"ok": False, "reason": "scheduler.disabled", **health_snapshot()}
    with _lock:
        if _thread and _thread.is_alive():
            return {"ok": True, "reason": "already_running", **health_snapshot()}
        _stop.clear()
        _set_health(scheduler_state=STATE_STARTING, enabled=True)
        _thread = threading.Thread(target=_loop, args=(cfg,), daemon=True, name="trading-day-scheduler")
        _thread.start()
    return {"ok": True, "reason": "started", **health_snapshot()}


def stop_scheduler() -> dict[str, Any]:
    global _thread
    _stop.set()
    t = _thread
    if t and t.is_alive():
        t.join(timeout=5)
    _thread = None
    _set_health(scheduler_state=STATE_STOPPED)
    return {"ok": True, **health_snapshot()}


def run_slot_now(
    cfg: dict[str, Any],
    *,
    cycle_type: str = SLOT_OPENING,
    slot: str | None = None,
    trading_date: str | None = None,
    force: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    if cycle_type == "CLOSING":
        cycle_type = SLOT_POST_CLOSE
    cal = load_trading_calendar(cfg)
    tz = ZoneInfo(scheduler_cfg(cfg)["timezone"])
    today = trading_date or (now or _local_now(tz)).date().isoformat()
    slot = slot or cycle_type
    if slot == "CLOSING":
        slot = SLOT_POST_CLOSE
    if force:
        slot = f"{slot}_FORCE_{new_run_id()[-8:]}"
    if scheduler_cfg(cfg)["run_on_trading_days"] and not cal.is_trading_day(date.fromisoformat(today)):
        return {"ok": False, "reason": "NOT_TRADING_DAY", "trading_date": today}
    scheduled_at = None
    for plan in planned_slots(cfg, date.fromisoformat(today)):
        if plan["slot"] == slot or (plan["cycle_type"] == cycle_type and slot == cycle_type):
            scheduled_at = plan["scheduled_at"].isoformat()
            break
    return _execute_slot(cfg, trading_date=today, cycle_type=cycle_type, slot=slot, scheduled_at=scheduled_at)


def process_due_at(cfg: dict[str, Any], now: datetime) -> dict[str, Any]:
    """Test helper: single-pass due + missed processing as of `now`."""
    cal = load_trading_calendar(cfg)
    today = now.date()
    _reset_today_counters(today.isoformat())
    if scheduler_cfg(cfg)["run_on_trading_days"] and not cal.is_trading_day(today):
        return {"ok": False, "reason": "NOT_TRADING_DAY", "executed": [], "missed": []}
    due, missed = _due_or_missed(cfg, now, cal)
    if missed:
        _mark_missed_slots(cfg, missed)
    executed = []
    for item in due:
        executed.append(_execute_slot(
            cfg, trading_date=today.isoformat(), cycle_type=item["cycle_type"],
            slot=item["slot"], scheduled_at=item.get("scheduled_at_iso"),
        ))
    _sync_today_slots_view(cfg, now)
    return {
        "ok": True, "executed": executed,
        "missed": [{"slot": m["slot"], "cycle_type": m["cycle_type"], "late_seconds": m["late_seconds"]} for m in missed],
        "today_slots": health_snapshot().get("today_slots"),
    }
