"""Trading-day production scheduler — independent of agent.autostart.

States: STOPPED | STARTING | RUNNING | PAUSED | MARKET_CLOSED | ERROR
Slots: PRE_OPEN | OPENING | INTRADAY | CLOSING

Does not change BUY thresholds. Fires agent.run_cycle with run_id + cycle_type.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import date, datetime, time as dtime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from ashare.calendar.trading_calendar import load_trading_calendar
from ashare.services.production_cycle import (
    IdempotencyStore,
    idempotency_key,
    new_run_id,
    record_production_run_meta,
)

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
SLOT_CLOSING = "CLOSING"

_lock = threading.Lock()
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
    "today_date": None,
    "missed_runs": [],
}


def scheduler_cfg(cfg: dict[str, Any]) -> dict[str, Any]:
    base = dict(cfg.get("scheduler") or {})
    return {
        "enabled": bool(base.get("enabled", True)),
        "timezone": str(base.get("timezone") or "Asia/Shanghai"),
        "market": str(base.get("market") or "SSE"),
        "run_on_trading_days": bool(base.get("run_on_trading_days", True)),
        "poll_sec": float(base.get("poll_sec") or 20),
        # HH:MM local
        "pre_open": str(base.get("pre_open") or "09:15"),
        "opening": str(base.get("opening") or "09:35"),
        "intraday": list(base.get("intraday") or ["10:30", "11:00", "14:00"]),
        "closing": str(base.get("closing") or "15:05"),
        "execute_cycles": bool(base.get("execute_cycles", True)),
    }


def health_snapshot() -> dict[str, Any]:
    with _lock:
        return dict(_health)


def _set_health(**kwargs: Any) -> None:
    with _lock:
        _health.update(kwargs)


def _parse_hhmm(s: str) -> dtime:
    parts = str(s).strip().split(":")
    return dtime(int(parts[0]), int(parts[1]) if len(parts) > 1 else 0)


def _local_now(tz: ZoneInfo) -> datetime:
    return datetime.now(tz)


def _due_slots(cfg: dict[str, Any], now: datetime, cal) -> list[tuple[str, str]]:
    """Return list of (cycle_type, scheduled_slot) due at `now` (within ±poll window)."""
    sc = scheduler_cfg(cfg)
    poll = float(sc["poll_sec"])
    today = now.date()
    if sc["run_on_trading_days"] and not cal.is_trading_day(today):
        return []
    candidates: list[tuple[str, str, dtime]] = [
        (SLOT_PRE_OPEN, SLOT_PRE_OPEN, _parse_hhmm(sc["pre_open"])),
        (SLOT_OPENING, SLOT_OPENING, _parse_hhmm(sc["opening"])),
        (SLOT_CLOSING, SLOT_CLOSING, _parse_hhmm(sc["closing"])),
    ]
    for i, hhmm in enumerate(sc["intraday"]):
        candidates.append((SLOT_INTRADAY, f"{SLOT_INTRADAY}_{i}_{hhmm}", _parse_hhmm(hhmm)))
    due = []
    for ctype, slot, t in candidates:
        target = datetime.combine(today, t, tzinfo=now.tzinfo)
        delta = (now - target).total_seconds()
        # fire once when we are within [0, poll*1.5] after scheduled time
        if 0 <= delta <= poll * 1.5:
            due.append((ctype, slot))
    return due


def _reset_today_counters(today: str) -> None:
    with _lock:
        if _health.get("today_date") != today:
            _health["today_date"] = today
            _health["today_runs"] = 0
            _health["today_success"] = 0
            _health["today_failed"] = 0


def _execute_slot(cfg: dict[str, Any], *, trading_date: str, cycle_type: str, slot: str) -> dict[str, Any]:
    from ashare.config import load_config
    from ashare.services.agent import run_cycle

    cfg = load_config(cfg.get("_config_path")) if cfg.get("_config_path") else cfg
    key = idempotency_key(trading_date, cycle_type, slot)
    store = IdempotencyStore(cfg)
    if store.is_done(key):
        prev = store.get(key) or {}
        logger.info("[SCHEDULER] skip idempotent key=%s run_id=%s", key, prev.get("run_id"))
        return {"skipped": True, "reason": "IDEMPOTENT", "run_id": prev.get("run_id"), "idempotency_key": key}

    run_id = new_run_id()
    _reset_today_counters(trading_date)
    with _lock:
        _health["today_runs"] = int(_health.get("today_runs") or 0) + 1
        _health["last_run_id"] = run_id
        _health["last_cycle_type"] = cycle_type
    t0 = time.time()
    ok = False
    err = ""
    result: dict[str, Any] = {}
    try:
        # Stash production context for research persist
        cfg = {**cfg, "_production_run_id": run_id, "_cycle_type": cycle_type, "_scheduled_slot": slot}
        logger.info(
            "[SCHEDULER] fire trading_date=%s cycle_type=%s slot=%s run_id=%s",
            trading_date,
            cycle_type,
            slot,
            run_id,
        )
        if scheduler_cfg(cfg).get("execute_cycles", True):
            result = run_cycle(cfg, reset_paper=False)
        else:
            result = {"dry_run": True, "run_id": run_id}
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
    meta = {
        "run_id": run_id,
        "trading_date": trading_date,
        "cycle_type": cycle_type,
        "scheduled_slot": slot,
        "idempotency_key": key,
        "success": ok,
        "error": err or None,
        "duration_sec": dur,
        "candidate_count": (research.get("candidate_union") or {}).get("n_union")
        or research.get("candidate_count"),
        "research_count": (research.get("candidate_union") or {}).get("n_research")
        or research.get("research_count"),
        "council_count": len(research.get("platform_reports") or []),
        "buy_count": sum(
            1 for d in (research.get("canonical_decisions") or []) if d.get("committee_approve")
        ),
        "recorded_at": datetime.now().astimezone().isoformat(),
    }
    try:
        record_production_run_meta(cfg, meta)
    except Exception:  # noqa: BLE001
        pass
    if ok:
        store.mark_done(key, run_id=run_id, meta={"cycle_type": cycle_type, "slot": slot})
        with _lock:
            _health["today_success"] = int(_health.get("today_success") or 0) + 1
            _health["last_success_at"] = datetime.now().astimezone().isoformat()
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
            _health["last_failure_at"] = datetime.now().astimezone().isoformat()
            _health["last_error"] = err
            _health["scheduler_state"] = STATE_ERROR
    return meta


def _loop(cfg: dict[str, Any]) -> None:
    sc = scheduler_cfg(cfg)
    tz = ZoneInfo(sc["timezone"])
    cal = load_trading_calendar(cfg)
    poll = float(sc["poll_sec"])
    _set_health(scheduler_state=STATE_RUNNING, enabled=True)
    logger.info("[SCHEDULER] started tz=%s poll_sec=%s", sc["timezone"], poll)
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
            else:
                if _health.get("scheduler_state") == STATE_MARKET_CLOSED:
                    _set_health(scheduler_state=STATE_RUNNING)
                for ctype, slot in _due_slots(cfg_live, now, cal):
                    _execute_slot(cfg_live, trading_date=today.isoformat(), cycle_type=ctype, slot=slot)
            # Missed-run detection: after closing slot time + 30min, if trading day and opening not done
            _check_missed(cfg_live, cal, now, sc)
        except Exception as exc:  # noqa: BLE001
            logger.exception("[SCHEDULER] loop error: %s", exc)
            _set_health(scheduler_state=STATE_ERROR, last_error=str(exc)[:200])
        _stop.wait(poll)
    _set_health(scheduler_state=STATE_STOPPED)
    logger.info("[SCHEDULER] stopped")


def _check_missed(cfg: dict[str, Any], cal, now: datetime, sc: dict[str, Any]) -> None:
    today = now.date()
    if not cal.is_trading_day(today):
        return
    closing = _parse_hhmm(sc["closing"])
    close_dt = datetime.combine(today, closing, tzinfo=now.tzinfo)
    if now < close_dt + timedelta(minutes=30):
        return
    store = IdempotencyStore(cfg)
    key = idempotency_key(today.isoformat(), SLOT_OPENING, SLOT_OPENING)
    if store.is_done(key):
        return
    missed = {
        "date": today.isoformat(),
        "expected_start": datetime.combine(today, _parse_hhmm(sc["opening"]), tzinfo=now.tzinfo).isoformat(),
        "actual_start": None,
        "reason": "MISSED_RUN",
        "slot": SLOT_OPENING,
    }
    with _lock:
        recent = list(_health.get("missed_runs") or [])
        if not any(m.get("date") == today.isoformat() and m.get("slot") == SLOT_OPENING for m in recent):
            recent.append(missed)
            _health["missed_runs"] = recent[-30:]
            logger.warning("[SCHEDULER] MISSED_RUN %s", missed)


def start_scheduler(cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """Start trading-day scheduler daemon (idempotent)."""
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
) -> dict[str, Any]:
    """Manual / test fire of a slot. force=True bypasses idempotency (uses unique slot suffix)."""
    cal = load_trading_calendar(cfg)
    tz = ZoneInfo(scheduler_cfg(cfg)["timezone"])
    today = trading_date or _local_now(tz).date().isoformat()
    slot = slot or cycle_type
    if force:
        slot = f"{slot}_FORCE_{new_run_id()[-8:]}"
    if scheduler_cfg(cfg)["run_on_trading_days"] and not cal.is_trading_day(date.fromisoformat(today)):
        return {"ok": False, "reason": "NOT_TRADING_DAY", "trading_date": today}
    return _execute_slot(cfg, trading_date=today, cycle_type=cycle_type, slot=slot)
