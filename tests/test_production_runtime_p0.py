"""P0 Production Runtime — scheduler, persistence, provenance, budgets."""

from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from ashare.calendar.trading_calendar import WeekdayTradingCalendar
from ashare.research.canonical_decision import build_canonical_decision
from ashare.research.session import ResearchSessionEngine, _normalize_chairman_source
from ashare.research.snapshot import SnapshotStore, build_snapshot
from ashare.services.production_cycle import (
    IdempotencyStore,
    PaperOrderIdempotencyStore,
    append_live_observation,
    idempotency_key,
    new_run_id,
    persist_production_report,
)
from ashare.services.production_observability import (
    analyze_calendar_coverage,
    classify_day_status,
    extract_gate_skip_cases,
)
from ashare.services.scheduler import (
    SLOT_INTRADAY,
    SLOT_OPENING,
    SLOT_POST_CLOSE,
    SLOT_PRE_OPEN,
    health_snapshot,
    run_slot_now,
    scheduler_cfg,
    start_scheduler,
    stop_scheduler,
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
            "execute_cycles": False,
            "poll_sec": 1,
            "max_late_seconds": 900,
        },
        "agent": {"autostart": False},
    }


class TestTradingCalendar:
    def test_weekday_and_weekend(self):
        cal = WeekdayTradingCalendar(closed_dates={date(2026, 10, 1)})
        assert cal.is_trading_day(date(2026, 8, 26))  # Wed
        assert not cal.is_trading_day(date(2026, 8, 23))  # Sun
        assert not cal.is_trading_day(date(2026, 10, 1))  # holiday file
        assert cal.next_trading_day(date(2026, 8, 21)) == date(2026, 8, 24)
        assert cal.previous_trading_day(date(2026, 8, 24)) == date(2026, 8, 21)

    def test_market_open_sessions(self):
        cal = WeekdayTradingCalendar()
        tz = ZoneInfo("Asia/Shanghai")
        open_am = datetime(2026, 8, 26, 10, 0, tzinfo=tz)
        lunch = datetime(2026, 8, 26, 12, 0, tzinfo=tz)
        assert cal.is_market_open(open_am)
        assert not cal.is_market_open(lunch)


class TestScheduler:
    def test_scheduler_cfg_defaults(self, tmp_cfg):
        sc = scheduler_cfg(tmp_cfg)
        assert sc["enabled"] is True
        assert sc["timezone"] == "Asia/Shanghai"

    def test_autostart_false_does_not_block_scheduler(self, tmp_cfg):
        assert tmp_cfg["agent"]["autostart"] is False
        assert scheduler_cfg(tmp_cfg)["enabled"] is True

    def test_disabled_scheduler_stays_stopped(self, tmp_cfg):
        stop_scheduler()
        tmp_cfg["scheduler"]["enabled"] = False
        out = start_scheduler(tmp_cfg)
        assert out["ok"] is False
        assert health_snapshot()["scheduler_state"] == "STOPPED"


class TestSchedulerIdempotency:
    def test_same_slot_once(self, tmp_cfg):
        store = IdempotencyStore(tmp_cfg)
        key = idempotency_key("2026-08-26", SLOT_OPENING, SLOT_OPENING)
        claim = store.claim_once(key, run_id="r1")
        assert claim.claimed
        store.mark_done(key, run_id="r1")
        assert store.is_done(key)
        assert store.get(key)["run_id"] == "r1"

    def test_run_slot_idempotent(self, tmp_cfg, monkeypatch):
        calls = []

        def fake_dispatch(cfg, **kwargs):
            calls.append(kwargs.get("run_id") or cfg.get("_production_run_id"))
            return {"platform_reports": [], "canonical_decisions": [], "full_council": True}

        monkeypatch.setattr("ashare.services.scheduler.dispatch_cycle", fake_dispatch)
        tmp_cfg["scheduler"]["execute_cycles"] = True
        d = date(2026, 8, 26)
        r1 = run_slot_now(tmp_cfg, cycle_type=SLOT_OPENING, slot=SLOT_OPENING, trading_date=d.isoformat())
        r2 = run_slot_now(tmp_cfg, cycle_type=SLOT_OPENING, slot=SLOT_OPENING, trading_date=d.isoformat())
        assert r1.get("success") is True or r1.get("run_id")
        assert r2.get("skipped") is True or r2.get("reason") == "IDEMPOTENT"
        assert len(calls) == 1


class TestProductionCyclePersistence:
    def test_run_id_unique(self):
        a = new_run_id()
        b = new_run_id()
        assert a != b
        assert "T" in a

    def test_report_no_overwrite(self, tmp_cfg):
        as_of = "2026-08-26"
        p1 = persist_production_report(
            tmp_cfg, {"as_of": as_of, "run_id": "20260826T093000-aaa1", "platform_reports": []}
        )
        p2 = persist_production_report(
            tmp_cfg, {"as_of": as_of, "run_id": "20260826T100000-bbb2", "platform_reports": []}
        )
        assert p1.exists() and p2.exists()
        assert p1 != p2
        day_dir = Path(tmp_cfg["_root"]) / "data" / "reports" / as_of
        runs = list(day_dir.glob("*.json"))
        assert len([p for p in runs if not p.name.startswith("_")]) == 2


class TestGateSkip:
    def test_not_rating(self, tmp_cfg):
        eng = object.__new__(ResearchSessionEngine)
        eng.cfg = tmp_cfg
        eng.research_cfg = {}
        rep = eng._gate_skip_report(
            {
                "symbol": "600000.SH",
                "gate": {"reason": "DEEP_BUDGET", "rank": 12, "passed": False},
                "candidate_score": 0.25,
            }
        )
        assert rep["decision"]["decision_status"] == "SKIPPED"
        assert rep["decision"]["research_rating"] is None
        assert rep["decision"]["skip_reason"] == "DEEP_BUDGET"


class TestDeepBudget:
    def test_priority_recorded(self, tmp_cfg):
        eng = object.__new__(ResearchSessionEngine)
        eng.cfg = tmp_cfg
        eng.research_cfg = {}
        rep = eng._gate_skip_report(
            {
                "symbol": "600000.SH",
                "candidate_score": 0.28,
                "leader_score": 0.4,
                "board_count": 2,
                "ml_prediction": 0.02,
                "profit_score": 0.3,
                "event_score": 0.2,
                "news_score": 0.15,
                "gate": {"reason": "DEEP_BUDGET", "rank": 15, "passed": False},
            }
        )
        pr = rep["research_priority"]
        assert pr["priority_rank"] == 15
        assert pr["candidate_score"] == 0.28
        assert pr["reason"] == "DEEP_BUDGET"


class TestLLMBudget:
    def test_budget_meta(self, tmp_cfg):
        eng = object.__new__(ResearchSessionEngine)
        eng.cfg = tmp_cfg
        eng.research_cfg = {"research_gate": {"max_llm_calls": 30}}
        rep = eng._budget_skip_report({"symbol": "600000.SH", "gate": {"rank": 3}}, llm_used=30)
        g = rep["gate"]
        assert g["reason"] == "LLM_BUDGET"
        assert g["budget_used"] == 30
        assert "budget_remaining" in g


class TestResearchSnapshotImmutable:
    def test_reuse_same_day(self, tmp_cfg):
        store = SnapshotStore(tmp_cfg)
        cand = {
            "symbol": "600000.SH",
            "name": "浦发",
            "as_of": "2026-08-26",
            "candidate_score": 0.3,
            "leader_score": 0.2,
            "ml_prediction": 0.01,
            "ml_prediction_status": "VALID",
            "profit_score": 0.2,
            "profit_status": "VALID",
            "event_score": 0.1,
            "event_status": "VALID",
            "news_score": 0.1,
            "news_status": "VALID",
        }
        snap1 = build_snapshot(cand, tmp_cfg)
        store.save(
            {
                **snap1,
                "report": {
                    "decision": {"research_rating": "WATCH", "decision_status": "COMPLETED"},
                    "chairman": {"rating": "WATCH", "source": "heuristic"},
                },
            }
        )
        eng = object.__new__(ResearchSessionEngine)
        eng.cfg = tmp_cfg
        eng.store = store
        r2 = eng._reuse_formal_report(store.load_formal_for_date("600000.SH", "2026-08-26"), cand)
        assert r2.get("snapshot_reused") is True
        assert r2.get("research_id") == snap1["research_id"]


class TestResearchRevision:
    def test_revision_on_break_limit(self, tmp_cfg):
        store = SnapshotStore(tmp_cfg)
        cand = {
            "symbol": "600001.SH",
            "as_of": "2026-08-26",
            "candidate_score": 0.3,
            "leader_score": 0.2,
        }
        s1 = build_snapshot(cand, tmp_cfg)
        store.save(s1)
        s2 = build_snapshot({**cand, "reassessment_trigger": "BREAK_LIMIT"}, tmp_cfg)
        assert int(s2.get("revision") or 0) == 2
        assert s2["revision_trigger"] == "BREAK_LIMIT"
        assert s2["research_id"] != s1["research_id"]


class TestLiveObservationAppend:
    def test_append_only(self, tmp_cfg):
        day = "2026-08-26"
        append_live_observation(tmp_cfg, {"symbol": "600000.SH", "as_of": day, "price": 10.0})
        append_live_observation(tmp_cfg, {"symbol": "600000.SH", "as_of": day, "price": 10.1})
        path = Path(tmp_cfg["_root"]) / "data" / "live_observations" / f"{day}.jsonl"
        lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        assert len(lines) == 2


class TestReconciliationIds:
    def test_recon_links(self, tmp_cfg):
        from ashare.services.state_reconciliation import build_market_state_bundle

        row = {
            "symbol": "600000.SH",
            "research_date": "2026-08-26",
            "research_id": "RTEST001",
            "live_status": "NORMAL",
            "live_price": 10.5,
            "close": 10.0,
            "trade_timing_action": "WATCH",
        }
        cfg = {**tmp_cfg, "_production_run_id": "run-xyz"}
        bundle = build_market_state_bundle(row, cfg=cfg, update_history=False)
        recon = bundle["reconciliation"]
        assert recon.get("research_snapshot_id") == "RTEST001"
        assert recon.get("production_run_id") == "run-xyz"
        assert recon.get("live_observation_id") or bundle["live_state"].get("observation_id")


class TestMissedRun:
    def test_classify_missed(self):
        st = classify_day_status(
            has_report=False,
            cycle_count=0,
            cycle_with_candidates=0,
            cycle_with_research=0,
            report_parse_ok=True,
            is_trading_day=True,
            scheduler_expected=True,
        )
        assert st == "MISSED_RUN"

    def test_non_trading(self):
        st = classify_day_status(
            has_report=False,
            cycle_count=0,
            cycle_with_candidates=0,
            cycle_with_research=0,
            report_parse_ok=True,
            is_trading_day=False,
        )
        assert st == "NOT_TRADING_DAY"


class TestRecoveryAfterRestart:
    def test_idempotency_survives_reload(self, tmp_cfg):
        store = IdempotencyStore(tmp_cfg)
        key = idempotency_key("2026-08-26", SLOT_INTRADAY, "INTRADAY_0_10:30")
        store.mark_done(key, run_id="r-open")
        store2 = IdempotencyStore(tmp_cfg)
        assert store2.is_done(key)


class TestChairmanProvenance:
    def test_normalize(self):
        assert _normalize_chairman_source("llm") == "LLM"
        assert _normalize_chairman_source("cache") == "CACHE"
        assert _normalize_chairman_source("heuristic") == "HEURISTIC"
        assert _normalize_chairman_source("x", llm_failed=True) == "LLM_FAILED"


class TestSignalProvenance:
    def test_snapshot_signal_status(self, tmp_cfg):
        snap = build_snapshot(
            {
                "symbol": "600000.SH",
                "as_of": "2026-08-26",
                "ml_prediction": None,
                "ml_prediction_status": "MISSING",
                "profit_score": None,
                "profit_status": "UNAVAILABLE",
                "event_score": 0.2,
                "event_status": "VALID",
                "news_score": None,
                "news_status": "FAILED",
            },
            tmp_cfg,
        )
        assert snap.get("ml_prediction_status") in {"MISSING", None} or snap.get("profit_status")
        # Must not coerce missing to 0 bearish
        assert snap.get("ml_prediction") is None or snap.get("ml_prediction_status") != "VALID"


class TestCandidateContract:
    def test_fields(self, tmp_cfg):
        snap = build_snapshot(
            {
                "symbol": "600000.SH",
                "as_of": "2026-08-26",
                "candidate_score": 0.22,
                "leader_score": 0.31,
                "gate": {"rank": 4, "research_tier": "DEEP_RESEARCH"},
            },
            tmp_cfg,
        )
        assert snap["symbol"] == "600000.SH"
        assert snap["as_of"] == "2026-08-26"
        assert snap["quant"]["factor_score"] == 0.22
        assert snap["quant"]["leader_score"] == 0.31
        assert snap.get("priority_rank") == 4
        assert snap.get("research_eligibility") == "DEEP_RESEARCH"


class TestCanonicalDecision:
    def test_skip_null_rating(self):
        d = build_canonical_decision(
            {
                "symbol": "600000.SH",
                "decision": {"decision_status": "SKIPPED", "research_rating": None, "skip_reason": "DEEP_BUDGET"},
                "chairman": {"source": "research_gate"},
                "gate": {"passed": False, "reason": "DEEP_BUDGET"},
            },
            as_of="2026-08-26",
            universe_row={},
            bar_like=None,
            risk_allow_fn=lambda x: (True, "ok"),
        )
        assert d["decision_status"] == "SKIPPED"
        assert d["research_rating"] is None
        assert d["committee_approve"] is False

    def test_links(self):
        d = build_canonical_decision(
            {
                "symbol": "600000.SH",
                "research_id": "RABC",
                "snapshot_id": "RABC",
                "production_run_id": "run1",
                "decision": {"research_rating": "WATCH", "action": "WATCH", "decision_status": "COMPLETED"},
                "chairman": {"rating": "WATCH", "trading_action": "WATCH", "source": "llm", "chairman_source": "LLM"},
                "gate": {"passed": True},
            },
            as_of="2026-08-26",
            universe_row={},
            bar_like=None,
            risk_allow_fn=lambda x: (True, "ok"),
        )
        assert d["production_run_id"] == "run1"
        assert d["research_snapshot_id"] == "RABC"
        assert d["committee_decision_id"]


class TestPaperOrderIdempotency:
    def test_one_order_per_decision(self, tmp_cfg):
        store = PaperOrderIdempotencyStore(tmp_cfg)
        store.mark("D123", {"order_id": 1, "symbol": "600000.SH"})
        assert store.get("D123")["order_id"] == 1


class TestCoverageAudit:
    def test_trading_vs_calendar(self, tmp_cfg):
        start = date(2026, 8, 24)
        end = date(2026, 8, 26)
        cov = analyze_calendar_coverage(
            start=start,
            end=end,
            reports=[{"as_of": "2026-08-25", "_as_of_date": "2026-08-25", "_report_file": "x"}],
            cycles=[],
            calendar=WeekdayTradingCalendar(),
        )
        assert cov["calendar_days"] == 3
        assert cov["trading_days"] == 3  # Mon Tue Wed
        assert "trading_day_coverage_pct" in cov


class TestSimulatedTradingDay:
    def test_four_cycles_one_snapshot(self, tmp_cfg, monkeypatch):
        """Simulate opening + 2 intraday + post_close without overwrite.

        Only OPENING runs full council; INTRADAY live-only; POST_CLOSE summary.
        """
        as_of = "2026-08-26"
        run_ids = []

        def fake_dispatch(cfg, **kwargs):
            rid = kwargs.get("run_id") or cfg.get("_production_run_id")
            ctype = kwargs.get("cycle_type")
            run_ids.append(rid)
            payload = {
                "as_of": as_of,
                "run_id": rid,
                "cycle_type": ctype,
                "platform_reports": [],
                "canonical_decisions": [],
                "full_council": ctype == SLOT_OPENING,
            }
            persist_production_report(cfg, payload)
            if ctype == SLOT_OPENING:
                store = SnapshotStore(cfg)
                snap = build_snapshot(
                    {"symbol": "600000.SH", "as_of": as_of, "candidate_score": 0.2, "leader_score": 0.2},
                    cfg,
                )
                store.save({**snap, "report": {"chairman": {"rating": "WATCH", "source": "heuristic"}}})
            append_live_observation(cfg, {"symbol": "600000.SH", "as_of": as_of, "price": 10.0})
            return payload

        monkeypatch.setattr("ashare.services.scheduler.dispatch_cycle", fake_dispatch)
        tmp_cfg["scheduler"]["execute_cycles"] = True
        slots = [
            (SLOT_OPENING, SLOT_OPENING),
            (SLOT_INTRADAY, "INTRADAY_0_10:00"),
            (SLOT_INTRADAY, "INTRADAY_1_10:30"),
            (SLOT_POST_CLOSE, SLOT_POST_CLOSE),
        ]
        for ctype, slot in slots:
            run_slot_now(tmp_cfg, cycle_type=ctype, slot=slot, trading_date=as_of)
        assert len(run_ids) == 4
        assert len(set(run_ids)) == 4
        day_dir = Path(tmp_cfg["_root"]) / "data" / "reports" / as_of
        assert len([p for p in day_dir.glob("*.json") if not p.name.startswith("_")]) == 4
        formal = list((Path(tmp_cfg["_root"]) / "data" / "research_snapshots").glob("_formal_*.json"))
        assert len(formal) == 1
        live = Path(tmp_cfg["_root"]) / "data" / "live_observations" / f"{as_of}.jsonl"
        assert len([ln for ln in live.read_text(encoding="utf-8").splitlines() if ln.strip()]) == 4
        # restart safety
        out2 = run_slot_now(tmp_cfg, cycle_type=SLOT_OPENING, slot=SLOT_OPENING, trading_date=as_of)
        assert out2.get("reason") == "IDEMPOTENT" or out2.get("skipped") is True


class TestProductionSignalContract:
    def test_report_signal_fields_present(self, tmp_cfg):
        payload = {
            "as_of": "2026-08-26",
            "run_id": new_run_id(),
            "signals": {
                "ml": {"status": "UNAVAILABLE", "value": None},
                "profit": {"status": "MISSING", "value": None},
                "event": {"status": "VALID", "value": 0.2},
                "news": {"status": "FAILED", "value": None, "error_code": "E1"},
                "valuation": {"status": "UNAVAILABLE", "value": None},
            },
            "platform_reports": [],
        }
        path = persist_production_report(tmp_cfg, payload)
        loaded = json.loads(path.read_text(encoding="utf-8"))
        for k in ("ml", "profit", "event", "news", "valuation"):
            assert k in loaded["signals"]
            assert "status" in loaded["signals"][k]
            assert loaded["signals"][k]["status"] != "REPORT_FIELD_ABSENT"
