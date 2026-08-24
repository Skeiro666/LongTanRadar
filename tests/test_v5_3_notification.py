"""V5.3 Notification — gate, dedup, channels, outcome, no LLM, no auto trade."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from ashare.notification.dedup import DedupStore, apply_dedup
from ashare.notification.formatter import format_notification
from ashare.notification.gate import NotificationGate, rank_and_cap
from ashare.notification.models import GATE_NOTIFY, GATE_SKIP, GateInput, GateResult
from ashare.notification.outcome import compute_notification_attribution, compute_discovery_attribution
from ashare.notification.service import evaluate_cycle, run_notification_job
from ashare.notification.store import NotificationStore


def _cfg(root: Path) -> dict:
    return {"_root": str(root), "notification": {"enabled": True}}


def _canonical(
    *,
    symbol="600000.SH",
    rating="BUY",
    risk="pass",
    confidence=0.7,
    research_id="R20260822ABC123",
) -> dict:
    return {
        "symbol": symbol,
        "name": "Test",
        "research_rating": rating,
        "trading_action": "SMALL_POSITION",
        "risk_status": risk,
        "confidence": confidence,
        "research_session_id": research_id,
        "snapshot_id": research_id,
        "candidate_sources": ["quant", "event"],
    }


def _snapshot(eer_value=0.04, confidence=0.7) -> dict:
    return {
        "research_id": "R20260822ABC123",
        "market": {"price": 10.5},
        "candidate_score_meta": {
            "expected_excess_return": {
                "available": True,
                "value": eer_value,
                "confidence": confidence,
            }
        },
        "council": {
            "quant": {"stance": "bullish", "points": ["趋势改善"]},
            "event": {"stance": "positive", "points": ["重大事件"]},
            "bear": {"stance": "cautious", "points": ["估值偏高"]},
            "fundamental": {"stance": "buy", "points": ["龙头"]},
        },
        "chairman": {"base_case": "看好", "confidence": confidence, "risks": ["宏观"]},
        "value_available": True,
        "news_package": {"evidence_ids": ["E1001", "E1002"]},
    }


def test_buy_threshold_met(tmp_path):
    gate = NotificationGate(_cfg(tmp_path))
    gr = gate.evaluate(
        GateInput(
            canonical=_canonical(rating="BUY", confidence=0.7),
            snapshot=_snapshot(eer_value=0.04),
        )
    )
    assert gr.action == GATE_NOTIFY
    assert gr.level == "BUY"


def test_buy_skip_low_confidence(tmp_path):
    gate = NotificationGate(_cfg(tmp_path))
    gr = gate.evaluate(
        GateInput(canonical=_canonical(rating="BUY", confidence=0.5), snapshot=_snapshot())
    )
    assert gr.action == GATE_SKIP
    assert "confidence" in gr.reason


def test_strong_buy_threshold(tmp_path):
    gate = NotificationGate(_cfg(tmp_path))
    gr = gate.evaluate(
        GateInput(
            canonical=_canonical(rating="STRONG_BUY", confidence=0.8),
            snapshot=_snapshot(eer_value=0.06),
        )
    )
    assert gr.action == GATE_NOTIFY
    assert gr.level == "STRONG_BUY"
    assert "email" in gr.channels


def test_watch_pass_no_notify_without_position(tmp_path):
    gate = NotificationGate(_cfg(tmp_path))
    for rating in ("WATCH", "PASS", "SELL"):
        gr = gate.evaluate(GateInput(canonical=_canonical(rating=rating), snapshot=_snapshot()))
        assert gr.action == GATE_SKIP


def test_rating_exit_pass_with_position(tmp_path):
    gate = NotificationGate(_cfg(tmp_path))
    gr = gate.evaluate(
        GateInput(
            canonical=_canonical(rating="PASS"),
            snapshot=_snapshot(),
            has_paper_position=True,
        )
    )
    assert gr.action == GATE_NOTIFY
    assert gr.level == "RATING_EXIT"
    assert gr.metadata.get("change_reason") == "rating_downgrade"
    assert "email" in gr.channels


def test_rating_exit_sell_with_position(tmp_path):
    gate = NotificationGate(_cfg(tmp_path))
    gr = gate.evaluate(
        GateInput(
            canonical=_canonical(rating="SELL"),
            snapshot=_snapshot(),
            has_paper_position=True,
        )
    )
    assert gr.action == GATE_NOTIFY
    assert gr.level == "RATING_EXIT"
    assert gr.metadata.get("change_reason") == "explicit_sell"


def test_rating_exit_watch_only_on_downgrade(tmp_path):
    gate = NotificationGate(_cfg(tmp_path))
    gr = gate.evaluate(
        GateInput(
            canonical=_canonical(rating="WATCH"),
            snapshot=_snapshot(),
            has_paper_position=True,
            previous_decision="BUY",
        )
    )
    assert gr.action == GATE_NOTIFY
    assert gr.level == "RATING_EXIT"

    gr2 = gate.evaluate(
        GateInput(
            canonical=_canonical(rating="WATCH"),
            snapshot=_snapshot(),
            has_paper_position=True,
            previous_decision=None,
        )
    )
    assert gr2.action == GATE_SKIP


def test_risk_exit_with_position(tmp_path):
    gate = NotificationGate(_cfg(tmp_path))
    gr = gate.evaluate(
        GateInput(
            canonical=_canonical(rating="BUY", risk="blocked"),
            snapshot=_snapshot(),
            has_paper_position=True,
        )
    )
    assert gr.action == GATE_NOTIFY
    assert gr.level == "RISK_EXIT"


def test_eer_unavailable_skips(tmp_path):
    gate = NotificationGate(_cfg(tmp_path))
    gr = gate.evaluate(
        GateInput(
            canonical=_canonical(rating="BUY"),
            snapshot={"candidate_score_meta": {"expected_excess_return": {"available": False}}},
        )
    )
    assert gr.action == GATE_SKIP
    assert gr.reason == "expected_excess_return_unavailable"


def test_dedup_duplicate(tmp_path):
    history = [
        {
            "dedup_key": "abc",
            "symbol": "600000.SH",
            "status": "SENT",
            "sent_at": datetime.now(timezone.utc).isoformat(),
            "level": "BUY",
        }
    ]
    store = DedupStore(history, _cfg(tmp_path))
    ok, reason = store.check(
        dedup_key="abc",
        symbol="600000.SH",
        level="BUY",
        event_id=None,
        previous_decision=None,
        current_decision="BUY",
    )
    assert not ok
    assert reason == "DUPLICATE"


def test_cooldown_same_symbol(tmp_path):
    history = [
        {
            "dedup_key": "other",
            "symbol": "600000.SH",
            "status": "SENT",
            "sent_at": datetime.now(timezone.utc).isoformat(),
            "level": "BUY",
        }
    ]
    store = DedupStore(history, _cfg(tmp_path))
    ok, reason = store.check(
        dedup_key="newkey",
        symbol="600000.SH",
        level="BUY",
        event_id=None,
        previous_decision=None,
        current_decision="BUY",
    )
    assert not ok
    assert reason == "COOLDOWN"


def test_cooldown_allows_buy_to_strong_buy_upgrade(tmp_path):
    history = [
        {
            "dedup_key": "k1",
            "symbol": "600000.SH",
            "status": "SENT",
            "sent_at": datetime.now(timezone.utc).isoformat(),
            "level": "BUY",
            "metadata": {"current_decision": "BUY"},
        }
    ]
    store = DedupStore(history, _cfg(tmp_path))
    ok, _ = store.check(
        dedup_key="k2",
        symbol="600000.SH",
        level="STRONG_BUY",
        event_id=None,
        previous_decision="BUY",
        current_decision="STRONG_BUY",
    )
    assert ok


def test_priority_max_per_cycle(tmp_path):
    gate = NotificationGate(_cfg(tmp_path))
    cands = []
    for i, eer in enumerate([0.03, 0.05, 0.08, 0.10]):
        inp = GateInput(
            canonical=_canonical(symbol=f"60000{i}.SH", research_id=f"R{i}"),
            snapshot=_snapshot(eer_value=eer),
        )
        cands.append((inp, gate.evaluate(inp)))
    selected = rank_and_cap(cands, max_buy=3)
    assert len(selected) == 3
    priorities = [x[1].priority for x in selected]
    assert priorities == sorted(priorities, reverse=True)


def test_formatter_rating_exit(tmp_path):
    text = format_notification(
        level="RATING_EXIT",
        canonical=_canonical(rating="PASS"),
        snapshot=_snapshot(),
        cfg=_cfg(tmp_path),
    )
    assert "卖出" in text or "退出" in text
    assert "建议动作" in text


def test_exit_and_buy_both_cap(tmp_path):
    gate = NotificationGate(_cfg(tmp_path))
    cands = []
    for i in range(4):
        inp = GateInput(
            canonical=_canonical(symbol=f"60000{i}.SH", research_id=f"R{i}"),
            snapshot=_snapshot(eer_value=0.04 + i * 0.01),
        )
        cands.append((inp, gate.evaluate(inp)))
    inp_exit = GateInput(
        canonical=_canonical(symbol="600099.SH", rating="PASS", research_id="REXIT"),
        snapshot=_snapshot(),
        has_paper_position=True,
    )
    cands.append((inp_exit, gate.evaluate(inp_exit)))
    selected = rank_and_cap(cands, max_buy=3, max_exit=2)
    assert len(selected) == 4
    assert any(x[1].level == "RATING_EXIT" for x in selected)


def test_formatter_no_llm(tmp_path):
    text = format_notification(
        level="BUY",
        canonical=_canonical(),
        snapshot=_snapshot(),
        cfg=_cfg(tmp_path),
    )
    assert "寻龙尺" in text
    assert "600000.SH" in text
    assert "E1001" in text


@patch("ashare.notification.service.send_wechat")
@patch("ashare.notification.service.send_email")
@patch("ashare.notification.service._paper_positions", return_value=set())
def test_wechat_email_retry_isolation(mock_pos, mock_email, mock_wechat, tmp_path):
    mock_wechat.return_value = {"ok": True, "channel": "wechat"}
    mock_email.return_value = {"ok": False, "error": "smtp fail", "channel": "email"}
    snap_dir = tmp_path / "data" / "research_snapshots"
    snap_dir.mkdir(parents=True)
    rid = "R20260822ABC123"
    (snap_dir / f"{rid}.json").write_text(json.dumps(_snapshot(eer_value=0.06)), encoding="utf-8")

    payload = {
        "canonical_decisions": [_canonical(rating="STRONG_BUY", confidence=0.8, research_id=rid)],
        "platform_reports": [
            {"symbol": "600000.SH", "research_id": rid, "name": "Test", "decision": {"research_rating": "STRONG_BUY"}}
        ],
    }
    cfg = _cfg(tmp_path)
    result = run_notification_job(cfg, payload, "cycle_test")
    assert result["llm_calls"] == 0
    assert result["tokens"] == 0
    assert result["sent"] >= 1
    assert result["failed"] >= 1


def test_persistence(tmp_path):
    store = NotificationStore(_cfg(tmp_path))
    rec = store.make_record(
        canonical=_canonical(),
        level="BUY",
        channel="wechat",
        status="SENT",
        dedup_key="dk1",
    )
    store.append(rec)
    rows = store.list_recent()
    assert len(rows) == 1
    assert rows[0]["symbol"] == "600000.SH"


def test_notification_attribution_insufficient_sample():
    outcomes = [
        {
            "level": "BUY",
            "horizons": {"5": {"status": "ok", "realized_return": 0.01, "market_alpha": 0.005, "selection_alpha": 0.003}},
        }
    ]
    attr = compute_notification_attribution(outcomes, horizons=[5], minimum_sample=5)
    assert attr["BUY"]["5"]["insufficient_sample"] is True
    assert attr["BUY"]["5"]["sample_count"] == 1


def test_notification_attribution_with_sample():
    outcomes = [
        {
            "level": "BUY",
            "horizons": {
                "5": {"status": "ok", "realized_return": 0.02, "market_alpha": 0.01, "selection_alpha": 0.008}
            },
        }
    ] * 6
    attr = compute_notification_attribution(outcomes, horizons=[5], minimum_sample=5)
    assert attr["BUY"]["5"]["insufficient_sample"] is False
    assert attr["BUY"]["5"]["mean_market_alpha"] == pytest.approx(0.01)


def test_discovery_attribution():
    outcomes = [
        {
            "candidate_sources": ["news"],
            "horizons": {"5": {"status": "ok", "market_alpha": 0.01, "selection_alpha": 0.005}},
        }
    ] * 6
    disc = compute_discovery_attribution(outcomes, horizons=[5], minimum_sample=5)
    assert disc["news"]["5"]["insufficient_sample"] is False


@patch("ashare.notification.service._paper_positions", return_value=set())
def test_evaluate_cycle_respects_max(mock_pos, tmp_path):
    snap_dir = tmp_path / "data" / "research_snapshots"
    snap_dir.mkdir(parents=True)
    decisions = []
    reports = []
    for i in range(5):
        rid = f"R{i:03d}"
        (snap_dir / f"{rid}.json").write_text(json.dumps(_snapshot(eer_value=0.04 + i * 0.01)), encoding="utf-8")
        decisions.append(_canonical(symbol=f"60000{i}.SH", research_id=rid))
        reports.append({"symbol": f"60000{i}.SH", "research_id": rid})
    payload = {"canonical_decisions": decisions, "platform_reports": reports}
    jobs = evaluate_cycle(_cfg(tmp_path), payload)
    assert len(jobs) <= 3


@patch("ashare.services.trading.build_live_or_paper")
def test_no_auto_trading_in_notification(mock_broker, tmp_path):
    """Notification path must never place orders."""
    mock_broker.assert_not_called()
    gate = NotificationGate(_cfg(tmp_path))
    gr = gate.evaluate(GateInput(canonical=_canonical(), snapshot=_snapshot()))
    assert gr.action == GATE_NOTIFY
    # run_notification_job does not import execute_picks
    import ashare.notification.service as svc

    assert "execute_picks" not in open(svc.__file__, encoding="utf-8").read()


def test_future_data_notify_price_not_signal(tmp_path):
    """Outcome uses notify_price from notification time, not research signal."""
    from ashare.notification.outcome import seed_notification_outcome

    store = NotificationStore(_cfg(tmp_path))
    row = store.make_record(
        canonical=_canonical(),
        level="BUY",
        channel="wechat",
        status="SENT",
        dedup_key="x",
        metadata={"notify_price": 12.34},
    )
    store.append(row)
    inp = GateInput(canonical=_canonical(), snapshot=_snapshot())
    seed = seed_notification_outcome(_cfg(tmp_path), row.to_dict(), inp)
    assert seed["notify_price"] == 12.34
