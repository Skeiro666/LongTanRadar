"""Scheduler correctness: atomic claim, late catch-up, missed slots, cycle dispatch."""

from __future__ import annotations

import threading
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from ashare.calendar.trading_calendar import WeekdayTradingCalendar
from ashare.services.production_cycle import AtomicIdempotencyStore, idempotency_key, new_run_id
from ashare.services.scheduler import (
    SLOT_OPENING,
    SLOT_POST_CLOSE,
    SLOT_PRE_OPEN,
    health_snapshot,
    planned_slots,
    process_due_at,
    run_slot_now,
    scheduler_cfg,
)
from ashare.services.scheduler_dispatch import (
    REASSESSMENT_TRIGGERS,
    dispatch_cycle,
    dispatch_summary,
    pending_reassessment_hits,
    run_live_observation_only,
    run_post_close,
    run_pre_open,
)


@pytest.fixture()
def tmp_cfg(tmp_path: Path) -> dict:
    return {
        "_root": tmp_path,
        "_force_file_claims": True,
        "scheduler": {
            "enabled": True,
            "timezone": "Asia/Shanghai",
            "run_on_trading_days": True,
            "execute_cycles": True,
            "poll_sec": 20,
            "max_late_seconds": 900,
            "pre_open": "09:15",
            "opening": "09:35",
            "intraday": ["10:30", "11:00", "14:00"],
            "closing": "15:05",
        },
        "agent": {"autostart": False},
    }


def _dt(day: str, hhmm: str) -> datetime:
    tz = ZoneInfo("Asia/Shanghai")
    h, m = hhmm.split(":")
    d = date.fromisoformat(day)
    return datetime(d.year, d.month, d.day, int(h), int(m), tzinfo=tz)


class TestAtomicClaim:
    def test_claim_once_exclusive(self, tmp_cfg):
        store = AtomicIdempotencyStore(tmp_cfg)
        key = idempotency_key("2026-08-26", "OPENING", "OPENING")
        a = store.claim_once(key, run_id="r1")
        b = store.claim_once(key, run_id="r2")
        assert a.claimed is True
        assert b.claimed is False
        assert b.reason == "IDEMPOTENT"

    def test_two_threads_one_winner(self, tmp_cfg, monkeypatch):
        calls = []
        lock = threading.Lock()

        def fake_dispatch(cfg, **kwargs):
            with lock:
                calls.append(kwargs.get("run_id"))
            return {"full_council": True, "action": "FULL_RESEARCH_COUNCIL"}

        monkeypatch.setattr("ashare.services.scheduler.dispatch_cycle", fake_dispatch)
        results = []

        def worker():
            results.append(
                run_slot_now(tmp_cfg, cycle_type=SLOT_OPENING, slot=SLOT_OPENING, trading_date="2026-08-26")
            )

        t1 = threading.Thread(target=worker)
        t2 = threading.Thread(target=worker)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        winners = [r for r in results if not r.get("skipped")]
        skipped = [r for r in results if r.get("skipped")]
        assert len(winners) == 1
        assert len(skipped) == 1
        assert len(calls) == 1


class TestLateWindow:
    def test_pre_open_on_time(self, tmp_cfg, monkeypatch):
        monkeypatch.setattr(
            "ashare.services.scheduler.dispatch_cycle",
            lambda cfg, **kw: {"full_council": False, "action": "PREPARE", "run_id": kw["run_id"]},
        )
        now = _dt("2026-08-26", "09:14")
        # at 09:14 nothing due yet
        out = process_due_at(tmp_cfg, now)
        assert out["executed"] == []
        # at exactly after 09:15
        out2 = process_due_at(tmp_cfg, _dt("2026-08-26", "09:15"))
        slots = [e.get("scheduled_slot") or e.get("cycle_type") for e in out2["executed"] if not e.get("skipped")]
        assert "PRE_OPEN" in slots

    def test_pre_open_catchup_within_max_late(self, tmp_cfg, monkeypatch):
        monkeypatch.setattr(
            "ashare.services.scheduler.dispatch_cycle",
            lambda cfg, **kw: {"full_council": False, "action": "PREPARE", "cycle_type": kw["cycle_type"]},
        )
        # 09:15:31 — within 900s
        out = process_due_at(tmp_cfg, _dt("2026-08-26", "09:15").replace(second=31))
        executed = [e for e in out["executed"] if not e.get("skipped")]
        assert any(e.get("cycle_type") == "PRE_OPEN" for e in executed)

    def test_pre_open_missed_after_max_late(self, tmp_cfg, monkeypatch):
        monkeypatch.setattr(
            "ashare.services.scheduler.dispatch_cycle",
            lambda cfg, **kw: {"full_council": False, "action": "PREPARE"},
        )
        # 09:31 → 16 min late > 900s
        out = process_due_at(tmp_cfg, _dt("2026-08-26", "09:31"))
        assert any(m["slot"] == "PRE_OPEN" for m in out["missed"])
        # PRE_OPEN should not be in successful executed full runs
        pre = [e for e in out["executed"] if e.get("cycle_type") == "PRE_OPEN" and not e.get("skipped")]
        assert pre == []
        store = AtomicIdempotencyStore(tmp_cfg)
        rec = store.get(idempotency_key("2026-08-26", "PRE_OPEN", "PRE_OPEN"))
        assert rec and rec.get("status") == "MISSED"


class TestIdempotentReplay:
    def test_opening_success_then_repeat(self, tmp_cfg, monkeypatch):
        monkeypatch.setattr(
            "ashare.services.scheduler.dispatch_cycle",
            lambda cfg, **kw: {"full_council": True, "action": "FULL_RESEARCH_COUNCIL"},
        )
        r1 = run_slot_now(tmp_cfg, cycle_type=SLOT_OPENING, trading_date="2026-08-26")
        r2 = run_slot_now(tmp_cfg, cycle_type=SLOT_OPENING, trading_date="2026-08-26")
        assert r1.get("success") is True or r1.get("status") == "SUCCESS"
        assert r2.get("skipped") is True
        assert r2.get("reason") == "IDEMPOTENT"


class TestNonTradingDay:
    def test_weekend_no_run(self, tmp_cfg):
        # 2026-08-23 is Sunday
        out = process_due_at(tmp_cfg, _dt("2026-08-23", "10:00"))
        assert out.get("reason") == "NOT_TRADING_DAY"


class TestRestartSafety:
    def test_restart_skips_success(self, tmp_cfg, monkeypatch):
        n = {"c": 0}

        def fake(cfg, **kw):
            n["c"] += 1
            return {"full_council": True, "action": "FULL"}

        monkeypatch.setattr("ashare.services.scheduler.dispatch_cycle", fake)
        run_slot_now(tmp_cfg, cycle_type=SLOT_OPENING, trading_date="2026-08-26")
        # simulate restart: new store instance, same root
        run_slot_now(tmp_cfg, cycle_type=SLOT_OPENING, trading_date="2026-08-26")
        assert n["c"] == 1


class TestDispatch:
    def test_dispatch_summary_marks_opening_full(self):
        s = dispatch_summary()
        assert s["OPENING"]["full_council"] is True
        assert s["PRE_OPEN"]["full_council"] is False
        assert s["POST_CLOSE"]["full_council"] is False

    def test_pre_open_no_council(self, tmp_cfg):
        out = run_pre_open(tmp_cfg, run_id="r-pre", trading_date="2026-08-26")
        assert out["full_council"] is False
        assert out["action"] == "PREPARE"

    def test_post_close_no_council(self, tmp_cfg):
        out = run_post_close(tmp_cfg, run_id="r-post", trading_date="2026-08-26")
        assert out["full_council"] is False
        assert out["action"] == "DAILY_SUMMARY"
        assert (Path(tmp_cfg["_root"]) / "data" / "daily_summaries" / "2026-08-26.json").exists()

    def test_intraday_no_trigger_no_council(self, tmp_cfg, monkeypatch):
        monkeypatch.setattr(
            "ashare.services.scheduler_dispatch.pending_reassessment_hits",
            lambda cfg: [],
        )
        out = dispatch_cycle(
            tmp_cfg, cycle_type="INTRADAY", run_id="r-i", trading_date="2026-08-26", execute=True
        )
        assert out["full_council"] is False
        assert out["action"] == "LIVE_OBSERVATION"

    def test_intraday_break_limit_triggers_reassessment(self, tmp_cfg, monkeypatch):
        monkeypatch.setattr(
            "ashare.services.scheduler_dispatch.pending_reassessment_hits",
            lambda cfg: [{"symbol": "600000.SH", "matched_triggers": ["BREAK_LIMIT"]}],
        )
        called = {}

        def fake_cycle(cfg, reset_paper=False):
            called["yes"] = True
            called["trigger"] = cfg.get("_reassessment_trigger")
            return {"platform_reports": [{"x": 1}], "canonical_decisions": []}

        monkeypatch.setattr("ashare.services.agent.run_cycle", fake_cycle)
        out = dispatch_cycle(
            tmp_cfg, cycle_type="INTRADAY", run_id="r-i2", trading_date="2026-08-26", execute=True
        )
        assert called.get("yes") is True
        assert out["full_council"] is True
        assert out["reassessment"] is True
        assert called["trigger"] == "BREAK_LIMIT"

    def test_post_close_slot_via_scheduler(self, tmp_cfg, monkeypatch):
        monkeypatch.setattr(
            "ashare.services.scheduler.dispatch_cycle",
            lambda cfg, **kw: {
                "full_council": False,
                "action": "DAILY_SUMMARY",
                "cycle_type": "POST_CLOSE",
            },
        )
        r = run_slot_now(tmp_cfg, cycle_type=SLOT_POST_CLOSE, trading_date="2026-08-26")
        assert r.get("full_council") is False


class TestPlannedSlots:
    def test_all_slots_named(self, tmp_cfg):
        plans = planned_slots(tmp_cfg, date(2026, 8, 26))
        names = [p["slot"] for p in plans]
        assert names[0] == "PRE_OPEN"
        assert names[1] == "OPENING"
        assert names[-1] == "POST_CLOSE"
        assert any(s.startswith("INTRADAY_0_") for s in names)
        assert "CLOSING" not in names


class TestHealthTodaySlots:
    def test_today_slots_after_process(self, tmp_cfg, monkeypatch):
        monkeypatch.setattr(
            "ashare.services.scheduler.dispatch_cycle",
            lambda cfg, **kw: {"full_council": kw["cycle_type"] == "OPENING", "action": kw["cycle_type"]},
        )
        process_due_at(tmp_cfg, _dt("2026-08-26", "09:40"))
        h = health_snapshot()
        slots = h.get("today_slots") or []
        assert slots
        by = {s["slot"]: s for s in slots}
        assert by["PRE_OPEN"]["status"] in {"SUCCESS", "MISSED"}
        assert "status" in by["OPENING"]
        assert "run_id" in by["OPENING"] or by["OPENING"]["status"] == "SCHEDULED"


class TestMaxLateConfig:
    def test_cfg_default(self, tmp_cfg):
        assert scheduler_cfg(tmp_cfg)["max_late_seconds"] == 900
