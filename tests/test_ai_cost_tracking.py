from __future__ import annotations

import json
from pathlib import Path

import pytest

from ashare.ai.client import LLMClient
from ashare.ai.cost_tracker import (
    AICostTracker,
    estimate_cost_usd,
    estimate_tokens,
    get_cost_tracker,
)


@pytest.fixture
def tmp_tracker(tmp_path: Path) -> AICostTracker:
    cfg = {
        "_root": str(tmp_path),
        "ai": {
            "cost_tracking": {
                "enabled": True,
                "log_path": "data/ai/usage.jsonl",
                "usd_per_1m": {
                    "default_input_per_1m": 1.0,
                    "default_output_per_1m": 2.0,
                    "models": {"test-model": {"input_per_1m": 0.5, "output_per_1m": 1.0}},
                },
            }
        },
    }
    return AICostTracker(cfg)


def test_estimate_tokens_mixed_text():
    assert estimate_tokens("") == 0
    assert estimate_tokens("hello") >= 1
    assert estimate_tokens("你好世界") >= 2


def test_estimate_cost_usd():
    rates = {"default_input_per_1m": 1.0, "default_output_per_1m": 2.0}
    cost = estimate_cost_usd("m", 1_000_000, 500_000, rates)
    assert cost == pytest.approx(2.0)


def test_record_and_cycle_summary(tmp_tracker: AICostTracker):
    tmp_tracker.begin_cycle("test_cycle")
    tmp_tracker.record(
        model="test-model",
        provider="test",
        input_tokens=1000,
        output_tokens=200,
        latency_ms=50.0,
        usage_source="actual",
        role="dragon",
        symbol="600000.SH",
        call_site="roundtable.role",
    )
    summary = tmp_tracker.cycle_summary("test_cycle")
    assert summary["n_calls"] == 1
    assert summary["input_tokens"] == 1000
    assert summary["output_tokens"] == 200
    assert summary["by_role"]["dragon"] == 1200
    assert summary["by_symbol"]["600000.SH"] == 1200
    assert tmp_tracker.log_path.exists()
    lines = tmp_tracker.log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["cycle_id"] == "test_cycle"
    assert row["usage_source"] == "actual"


def test_efficiency_metrics(tmp_tracker: AICostTracker):
    tmp_tracker.begin_cycle("eff_cycle")
    tmp_tracker.record(
        model="m",
        provider="p",
        input_tokens=1000,
        output_tokens=500,
        latency_ms=10.0,
        usage_source="actual",
        research_session_id="RTEST001",
    )
    cycle = tmp_tracker.cycle_summary("eff_cycle")
    eff = tmp_tracker.efficiency_metrics(
        cycle,
        {"n_candidates": 10, "n_research": 5, "n_buys": 2},
    )
    assert eff["tokens_per_candidate"] == 150.0
    assert eff["tokens_per_buy"] == 750.0
    assert eff["cost_per_buy"] is not None
    assert "unknown" in cycle["role_cost"]
    assert cycle["total_calls"] == 1


def test_aicost_ledger_alias():
    from ashare.ai.cost_tracker import AICostLedger, AICostTracker

    assert AICostLedger is AICostTracker


def test_record_cache_save(tmp_tracker: AICostTracker):
    tmp_tracker.begin_cycle("cache_cycle")
    tmp_tracker.record_cache_save(
        estimated_tokens=500,
        call_site="strategy.ai_select",
        role="ai_select",
    )
    summary = tmp_tracker.cycle_summary("cache_cycle")
    assert summary["cache_saved_tokens"] == 500
    assert summary["n_cache_events"] == 1


def test_client_records_usage(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    cfg = {
        "_root": str(tmp_path),
        "ai": {
            "provider": "test",
            "base_url": "http://localhost",
            "model": "test-model",
            "api_key_env": "MISSING_KEY",
            "cost_tracking": {"enabled": True, "log_path": "data/ai/usage.jsonl"},
        },
    }
    get_cost_tracker(cfg).begin_cycle("client_test")
    client = LLMClient(
        provider="test",
        model="test-model",
        base_url="http://localhost",
        api_key="test-key",
        timeout_sec=5,
        use_sdk=False,
    )

    def fake_http(kwargs: dict) -> tuple[str, dict]:
        return '{"ok": true}', {"prompt_tokens": 10, "completion_tokens": 5}

    monkeypatch.setattr(client, "_chat_via_http", fake_http)
    client.chat(
        "sys",
        "user",
        json_mode=True,
        role="dragon",
        call_site="test.site",
    )
    tracker = get_cost_tracker()
    summary = tracker.cycle_summary("client_test")
    assert summary["n_calls"] == 1
    assert summary["input_tokens"] == 10
    assert summary["output_tokens"] == 5
