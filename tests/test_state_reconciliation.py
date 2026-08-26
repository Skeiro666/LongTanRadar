"""State Reconciliation: Research Snapshot vs Live Market (immutable research)."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from ashare.research.intel_package import slim_roundtable_candidate
from ashare.services.state_reconciliation import (
    TRIGGER_BREAK_LIMIT,
    TRIGGER_BREAK_LIMIT_PERSISTED,
    TRIGGER_LIVE_LIMIT_UP,
    TRIGGER_LIVE_QUOTE_STALE,
    TRIGGER_REBOUND_TO_LIMIT_UP,
    TRIGGER_RESEARCH_LIVE_DIVERGENCE,
    TRIGGER_ROUND_TABLE_REASSESS_REQUIRED,
    TRIGGER_STATE_RECOVERED,
    attach_reconciliation_overlay,
    build_market_state_bundle,
    enqueue_reassessment,
    pending_reassessments,
    reconcile,
    reset_reconciliation_state,
    update_live_history,
)

_TZ = ZoneInfo("Asia/Shanghai")


def _cfg(tmp_path=None):
    root = str(tmp_path) if tmp_path is not None else "."
    return {
        "_root": root,
        "data": {
            "live_quote_stale_seconds": 90,
            "live": {
                "break_limit_reassess_seconds": 300,
                "break_limit_invalidation_seconds": 900,
                "break_limit_rebound_seconds": 180,
                "price_divergence_pct": 3.0,
                "enable_roundtable_reassessment": True,
                "reconciliation_version": 1,
            },
        },
    }


def test_limit_up_consistent():
    reset_reconciliation_state()
    research = {
        "research_date": "2026-08-25",
        "board_count": 3,
        "trade_timing_action": "BUY_READY",
        "research_limit_up": True,
        "leader_score": 0.95,
        "stage": "ACCELERATION",
    }
    live = {
        "live_price": 11.0,
        "live_limit_up_price": 11.0,
        "live_status": "LIMIT_UP",
        "live_updated_at": datetime.now(_TZ).isoformat(timespec="seconds"),
    }
    out = reconcile(research, live, {}, cfg=_cfg())
    assert out["state"] == "CONSISTENT"
    assert TRIGGER_LIVE_LIMIT_UP in out["trigger_codes"]
    assert out["reassessment"] in {"NONE", "RECOVERED"}


def test_break_limit_short():
    reset_reconciliation_state()
    now = datetime.now(_TZ)
    research = {
        "research_date": "2026-08-25",
        "board_count": 3,
        "research_limit_up": True,
        "trade_timing_action": "BUY_READY",
    }
    live = {
        "live_price": 10.7,
        "live_limit_up_price": 11.0,
        "live_status": "BREAK_LIMIT",
        "live_updated_at": now.isoformat(timespec="seconds"),
    }
    hist = update_live_history("600785.SH", live_status="LIMIT_UP", live_price=11.0, now=now - timedelta(minutes=2))
    hist = update_live_history("600785.SH", live_status="BREAK_LIMIT", live_price=10.7, now=now - timedelta(seconds=30))
    out = reconcile(research, live, hist, cfg=_cfg(), now=now)
    assert out["state"] == "DEGRADED"
    assert TRIGGER_BREAK_LIMIT in out["trigger_codes"]
    assert out["reassessment"] == "CANDIDATE"
    assert TRIGGER_BREAK_LIMIT_PERSISTED not in out["trigger_codes"]


def test_break_limit_rebound():
    reset_reconciliation_state()
    now = datetime.now(_TZ)
    update_live_history("600785.SH", live_status="LIMIT_UP", live_price=11.0, now=now - timedelta(minutes=10))
    update_live_history("600785.SH", live_status="BREAK_LIMIT", live_price=10.8, now=now - timedelta(minutes=5))
    hist = update_live_history("600785.SH", live_status="LIMIT_UP", live_price=11.0, now=now)
    research = {"research_limit_up": True, "board_count": 3, "trade_timing_action": "BUY_READY"}
    live = {"live_price": 11.0, "live_limit_up_price": 11.0, "live_status": "LIMIT_UP"}
    out = reconcile(research, live, hist, cfg=_cfg(), now=now)
    assert out["state"] == "CONSISTENT"
    assert TRIGGER_REBOUND_TO_LIMIT_UP in out["trigger_codes"]
    assert TRIGGER_STATE_RECOVERED in out["trigger_codes"]
    assert out["reassessment"] == "RECOVERED"


def test_break_limit_persisted():
    reset_reconciliation_state()
    now = datetime.now(_TZ)
    update_live_history("600785.SH", live_status="LIMIT_UP", live_price=11.0, now=now - timedelta(minutes=20))
    hist = update_live_history(
        "600785.SH", live_status="BREAK_LIMIT", live_price=10.85, now=now - timedelta(seconds=400)
    )
    # Keep status BREAK_LIMIT with first_seen in the past
    hist["first_seen_break_limit_at"] = now - timedelta(seconds=400)
    hist["last_live_status"] = "BREAK_LIMIT"
    research = {"research_limit_up": True, "board_count": 3, "trade_timing_action": "BUY_READY"}
    live = {"live_price": 10.85, "live_limit_up_price": 11.0, "live_status": "BREAK_LIMIT"}
    out = reconcile(research, live, hist, cfg=_cfg(), now=now)
    assert out["state"] == "DEGRADED"
    assert TRIGGER_BREAK_LIMIT_PERSISTED in out["trigger_codes"]
    assert out["reassessment"] == "REQUIRED"
    assert TRIGGER_ROUND_TABLE_REASSESS_REQUIRED in out["trigger_codes"]


def test_break_limit_invalidated(tmp_path):
    reset_reconciliation_state()
    now = datetime.now(_TZ)
    hist = {
        "first_seen_break_limit_at": now - timedelta(seconds=1000),
        "last_live_status": "BREAK_LIMIT",
        "saw_break_after_limit_up": True,
        "consecutive_break_limit_observations": 40,
    }
    research = {
        "research_limit_up": True,
        "board_count": 3,
        "trade_timing_action": "BUY_READY",
        "leader_score": 0.95,
    }
    # ~5.5% below limit-up price
    live = {"live_price": 10.4, "live_limit_up_price": 11.0, "live_status": "BREAK_LIMIT"}
    out = reconcile(research, live, hist, cfg=_cfg(tmp_path), now=now)
    assert out["state"] == "INVALIDATED"
    assert out["severity"] == "CRITICAL"
    assert TRIGGER_RESEARCH_LIVE_DIVERGENCE in out["trigger_codes"]
    assert TRIGGER_ROUND_TABLE_REASSESS_REQUIRED in out["trigger_codes"]


def test_stale_quote_does_not_invalidate():
    reset_reconciliation_state()
    research = {"research_limit_up": True, "board_count": 3, "trade_timing_action": "BUY_READY"}
    live = {
        "live_price": 10.5,
        "live_limit_up_price": 11.0,
        "live_status": "STALE",
    }
    out = reconcile(research, live, {}, cfg=_cfg())
    assert out["state"] == "UNKNOWN"
    assert TRIGGER_LIVE_QUOTE_STALE in out["trigger_codes"]
    assert out["state"] != "INVALIDATED"
    assert TRIGGER_ROUND_TABLE_REASSESS_REQUIRED not in out["trigger_codes"]


def test_research_snapshot_immutable():
    reset_reconciliation_state()
    row = {
        "symbol": "600785.SH",
        "research_date": "2026-08-25",
        "board_count": 3,
        "leader_score": 0.86,
        "stage": "EXTREME",
        "research_limit_up": True,
        "research_price": 11.78,
        "trade_timing_action": "BUY_READY",
        "status_reason": "limit_up_block",
        "live_price": 10.5,
        "live_change_pct": 5.0,
        "live_limit_up_price": 12.96,
        "live_status": "BREAK_LIMIT",
        "live_updated_at": datetime.now(_TZ).isoformat(timespec="seconds"),
    }
    before = {
        "board_count": row["board_count"],
        "leader_score": row["leader_score"],
        "stage": row["stage"],
        "research_date": row["research_date"],
        "research_limit_up": row["research_limit_up"],
        "research_price": row["research_price"],
    }
    attach_reconciliation_overlay([row], cfg=_cfg())
    for k, v in before.items():
        assert row[k] == v
    assert row["reconciliation_state"] in {"DEGRADED", "INVALIDATED", "UNKNOWN", "CONSISTENT"}


def test_roundtable_uses_both_states():
    reset_reconciliation_state()
    cand = {
        "symbol": "600785.SH",
        "name": "新华百货",
        "board_count": 3,
        "quant": {"score": 0.8, "close": 11.78},
        "market_state_bundle": {
            "research_state": {
                "research_date": "2026-08-25",
                "board_count": 3,
                "trade_timing_action": "BUY_READY",
                "research_limit_up": True,
            },
            "live_state": {"live_price": 10.5, "live_status": "BREAK_LIMIT"},
            "reconciliation": {
                "state": "DEGRADED",
                "severity": "WARNING",
                "trigger_codes": [TRIGGER_BREAK_LIMIT],
            },
            "context": {
                "research_date": "2026-08-25",
                "live_observed_at": "2026-08-26T10:25:31+08:00",
                "reconciliation_version": 1,
            },
        },
    }
    slim = slim_roundtable_candidate(cand, "dragon", cfg={"research": {"context_compression": {"enabled": True}}})
    assert "market_state_advisory" in slim or "live_market_state" in slim
    assert slim.get("historical_research") or (slim.get("market_state_advisory") or {}).get("historical_research")
    assert slim.get("live_market_state") or (slim.get("market_state_advisory") or {}).get("live_market_state")
    assert slim.get("state_reconciliation") or (slim.get("market_state_advisory") or {}).get("state_reconciliation")
    # Historical board_count still present as research field on candidate slim
    assert slim.get("board_count") == 3


def test_no_buy_gate_bypass():
    """Reconciliation must never emit a trade approval / BUY action."""
    reset_reconciliation_state()
    research = {"research_limit_up": True, "board_count": 3, "trade_timing_action": "BUY_READY"}
    live = {"live_price": 11.0, "live_limit_up_price": 11.0, "live_status": "LIMIT_UP"}
    out = reconcile(research, live, {}, cfg=_cfg())
    assert "committee_approve" not in out
    assert "trading_action" not in out
    assert out.get("state") == "CONSISTENT"
    # Even invalidated is advisory only
    live2 = {"live_price": 10.0, "live_limit_up_price": 11.0, "live_status": "BREAK_LIMIT"}
    hist = {
        "first_seen_break_limit_at": datetime.now(_TZ) - timedelta(seconds=1200),
        "last_live_status": "BREAK_LIMIT",
    }
    out2 = reconcile(research, live2, hist, cfg=_cfg())
    assert out2["state"] == "INVALIDATED"
    assert "BUY" not in str(out2.get("trigger_codes"))
    assert out2.get("triggered") is True  # reassessment flag, not buy


def test_reassessment_idempotent(tmp_path):
    reset_reconciliation_state()
    cfg = _cfg(tmp_path)
    recon = {
        "state": "INVALIDATED",
        "severity": "CRITICAL",
        "reason": "test",
        "trigger_codes": [TRIGGER_ROUND_TABLE_REASSESS_REQUIRED, TRIGGER_RESEARCH_LIVE_DIVERGENCE],
    }
    k1 = enqueue_reassessment(
        symbol="600785.SH",
        research_date="2026-08-25",
        trigger_codes=recon["trigger_codes"],
        reconciliation=recon,
        cfg=cfg,
    )
    k2 = enqueue_reassessment(
        symbol="600785.SH",
        research_date="2026-08-25",
        trigger_codes=recon["trigger_codes"],
        reconciliation=recon,
        cfg=cfg,
    )
    assert k1 == k2
    pending = pending_reassessments(cfg, symbol="600785.SH")
    assert len(pending) == 1


def test_bundle_preserves_research_fields():
    reset_reconciliation_state()
    row = {
        "symbol": "600785.SH",
        "research_date": "2026-08-25",
        "board_count": 3,
        "leader_score": 0.9,
        "stage": "EXTREME",
        "research_limit_up": True,
        "trade_timing_action": "BUY_READY",
        "live_price": 11.0,
        "live_limit_up_price": 11.0,
        "live_status": "LIMIT_UP",
        "live_updated_at": datetime.now(_TZ).isoformat(timespec="seconds"),
    }
    bundle = build_market_state_bundle(row, cfg=_cfg(), update_history=True)
    assert bundle["research_state"]["board_count"] == 3
    assert bundle["research_state"]["leader_score"] == 0.9
    assert bundle["live_state"]["live_status"] == "LIMIT_UP"
    assert bundle["reconciliation"]["state"] == "CONSISTENT"
    assert bundle["context"]["reconciliation_version"] == 1
    assert row["board_count"] == 3
