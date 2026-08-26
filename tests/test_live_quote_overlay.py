"""Tests for LeaderMonitor Live Quote Overlay (research isolation)."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from ashare.services.live_quote_overlay import (
    attach_live_quote_overlay,
    build_live_fields,
    classify_live_status,
    reset_live_quote_cache,
)
from ashare.symbols import limit_bound_prices


_TZ = ZoneInfo("Asia/Shanghai")


def test_limit_bound_prices_main_board():
    up, down = limit_bound_prices(10.0, "600785.SH", is_st=False)
    assert up == 11.0
    assert down == 9.0


def test_limit_bound_prices_st():
    up, down = limit_bound_prices(10.0, "600785.SH", is_st=True)
    assert up == 10.5
    assert down == 9.5


def test_classify_limit_up():
    st = classify_live_status(
        price=11.0,
        limit_up_price=11.0,
        limit_down_price=9.0,
        change_pct=10.0,
        research_limit_up=True,
        updated_at=datetime.now(_TZ),
        stale_seconds=90,
    )
    assert st == "LIMIT_UP"


def test_classify_break_limit_keeps_research_context():
    st = classify_live_status(
        price=10.5,
        limit_up_price=11.0,
        limit_down_price=9.0,
        change_pct=5.0,
        research_limit_up=True,
        updated_at=datetime.now(_TZ),
        stale_seconds=90,
    )
    assert st == "BREAK_LIMIT"


def test_classify_unknown_no_price():
    assert (
        classify_live_status(
            price=None,
            limit_up_price=None,
            limit_down_price=None,
            change_pct=None,
            research_limit_up=True,
            updated_at=None,
        )
        == "UNKNOWN"
    )


def test_classify_stale():
    old = datetime.now(_TZ) - timedelta(seconds=200)
    st = classify_live_status(
        price=10.5,
        limit_up_price=11.0,
        limit_down_price=9.0,
        change_pct=5.0,
        research_limit_up=True,
        updated_at=old,
        stale_seconds=90,
    )
    assert st == "STALE"


def test_build_live_fields_break_limit_does_not_touch_research():
    row = {
        "symbol": "600785.SH",
        "name": "新华百货",
        "board_count": 3,
        "status_reason": "limit_up_block;stage=EXTREME",
        "research_date": "2026-08-25",
        "leader_score": 0.86,
    }
    quote = {
        "symbol": "600785.SH",
        "price": 12.51,
        "prev_close": 11.78,
        "change_pct": 6.2,
        "is_st": False,
        "name": "新华百货",
    }
    live = build_live_fields(
        row,
        quote,
        updated_at=datetime.now(_TZ),
        stale_seconds=90,
    )
    assert live["live_status"] == "BREAK_LIMIT"
    assert live["live_is_limit_up"] is False
    assert live["research_limit_up"] is True
    assert live["live_price"] == 12.51
    assert live["live_limit_up_price"] == limit_bound_prices(11.78, "600785.SH")[0]
    # Research fields on original row untouched by build_live_fields
    assert row["board_count"] == 3
    assert "limit_up_block" in row["status_reason"]


def test_attach_overlay_preserves_board_count(monkeypatch):
    reset_live_quote_cache()
    row = {
        "symbol": "600785.SH",
        "board_count": 3,
        "status_reason": "limit_up_block",
        "leader_score": 0.86,
        "focus_tier": "A",
    }
    fake_quotes = {
        "600785.SH": {
            "symbol": "600785.SH",
            "price": 12.51,
            "prev_close": 11.78,
            "change_pct": 6.2,
            "is_st": False,
            "name": "新华百货",
        }
    }

    monkeypatch.setattr(
        "ashare.data.akshare_source.fetch_spot_quotes",
        lambda symbols: fake_quotes,
    )
    monkeypatch.setattr(
        "ashare.services.live_quote_overlay.is_a_share_session",
        lambda now=None: True,
    )

    out = attach_live_quote_overlay(
        [row],
        cfg={"data": {"live_quote_stale_seconds": 90}},
        research_date="2026-08-25",
    )
    assert out[0]["board_count"] == 3
    assert out[0]["leader_score"] == 0.86
    assert out[0]["research_date"] == "2026-08-25"
    assert out[0]["research_limit_up"] is True
    assert out[0]["live_price"] == 12.51
    assert out[0]["live_status"] == "BREAK_LIMIT"
    assert abs(float(out[0]["live_change_pct"]) - 6.2) < 1e-6
    reset_live_quote_cache()


def test_attach_overlay_unknown_when_no_quote(monkeypatch):
    reset_live_quote_cache()
    row = {"symbol": "600785.SH", "board_count": 3, "status_reason": "limit_up_block"}
    monkeypatch.setattr("ashare.data.akshare_source.fetch_spot_quotes", lambda symbols: {})
    monkeypatch.setattr(
        "ashare.services.live_quote_overlay.is_a_share_session",
        lambda now=None: True,
    )
    out = attach_live_quote_overlay([row], cfg={}, research_date="2026-08-25")
    assert out[0]["board_count"] == 3
    assert out[0]["live_status"] == "UNKNOWN"
    assert out[0]["live_price"] is None
    reset_live_quote_cache()


def test_build_leader_monitor_adds_live_without_mutating_research(monkeypatch, tmp_path):
    reset_live_quote_cache()
    report = {
        "as_of": "2026-08-25",
        "candidate_union": {
            "leader_pipeline": {
                "focus_watchlist": {
                    "600785.SH": {
                        "symbol": "600785.SH",
                        "name": "新华百货",
                        "board_count": 3,
                        "leader_score": 0.86,
                        "lifecycle": "FOCUS",
                        "trade_timing_action": "WAIT",
                        "status_reason": "limit_up_block",
                        "focus_tier": "A",
                    }
                },
                "dashboard": {},
                "focus_stats": {},
            }
        },
        "platform_reports": [],
        "canonical_decisions": [],
    }
    cfg = {
        "_root": str(tmp_path),
        "data": {"live_quote_stale_seconds": 90},
    }
    (tmp_path / "data" / "reports").mkdir(parents=True)
    (tmp_path / "config").mkdir(parents=True)
    # minimal leader yaml for load_yaml_config
    (tmp_path / "config" / "leader.yaml").write_text(
        "enabled: true\nresearch_only: true\nproduct:\n  positioning: test\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "ashare.data.akshare_source.fetch_spot_quotes",
        lambda symbols: {
            "600785.SH": {
                "symbol": "600785.SH",
                "price": 12.51,
                "prev_close": 11.78,
                "change_pct": 6.2,
                "is_st": False,
                "name": "新华百货",
            }
        },
    )
    monkeypatch.setattr(
        "ashare.services.live_quote_overlay.is_a_share_session",
        lambda now=None: True,
    )

    from ashare.services.leader_monitor import build_leader_monitor

    pack = build_leader_monitor(cfg, report=report)
    rows = (pack.get("buckets") or {}).get("FOCUS") or []
    assert rows, "expected FOCUS bucket rows"
    row = rows[0]
    assert row["board_count"] == 3
    assert row["research_date"] == "2026-08-25"
    assert row["research_limit_up"] is True
    assert row["live_status"] == "BREAK_LIMIT"
    assert row["live_price"] == 12.51
    assert pack["research_date"] == "2026-08-25"
    # report object research fields not rewritten into a mutated snapshot file
    assert report["as_of"] == "2026-08-25"
    assert (
        report["candidate_union"]["leader_pipeline"]["focus_watchlist"]["600785.SH"]["board_count"]
        == 3
    )
    reset_live_quote_cache()
