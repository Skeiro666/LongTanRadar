"""P0 production observability audit helpers (read-only, no threshold changes)."""

from __future__ import annotations

from datetime import date

from ashare.services.production_observability import (
    analyze_calendar_coverage,
    analyze_council_breakdown,
    analyze_execution_chain,
    categorize_gate_skip,
    classify_day_status,
    extract_deep_budget_cases,
    extract_gate_skip_cases,
)


def test_categorize_gate_skip():
    assert categorize_gate_skip("DEEP_BUDGET") == "DEEP_BUDGET"
    assert categorize_gate_skip("LLM_BUDGET") == "LLM_BUDGET"
    assert categorize_gate_skip("MISSING_ML_DATA") == "MISSING_SIGNAL"


def test_classify_day_status():
    assert classify_day_status(has_report=False, cycle_count=0, cycle_with_candidates=0, cycle_with_research=0, report_parse_ok=True) == "NOT_RUN"
    assert classify_day_status(has_report=True, cycle_count=3, cycle_with_candidates=2, cycle_with_research=2, report_parse_ok=True) in {
        "REPORT_OVERWRITTEN",
        "HAS_REPORT_OVERWRITTEN",
    }
    assert classify_day_status(has_report=False, cycle_count=2, cycle_with_candidates=2, cycle_with_research=2, report_parse_ok=True) in {
        "RUNNING_NO_REPORT",
        "RUN_NO_PERSISTED_REPORT",
    }
    assert classify_day_status(
        has_report=False,
        cycle_count=0,
        cycle_with_candidates=0,
        cycle_with_research=0,
        report_parse_ok=True,
        is_trading_day=False,
    ) == "NOT_TRADING_DAY"
    assert classify_day_status(
        has_report=False,
        cycle_count=0,
        cycle_with_candidates=0,
        cycle_with_research=0,
        report_parse_ok=True,
        is_trading_day=True,
        scheduler_expected=True,
    ) == "MISSED_RUN"


def test_coverage_and_gate_skip_from_fixture_reports():
    reports = [
        {
            "_as_of_date": "2026-08-25",
            "as_of": "2026-08-25",
            "candidate_union": {
                "universe": [
                    {
                        "symbol": "600000.SH",
                        "candidate_score": 0.5,
                        "leader_score": 0.4,
                        "board_count": 2,
                        "in_council": True,
                    }
                ]
            },
            "platform_reports": [
                {
                    "symbol": "600000.SH",
                    "name": "测试",
                    "rating": "GATE_SKIP",
                    "action": "NO_ACTION",
                    "gate": {
                        "passed": False,
                        "reason": "DEEP_BUDGET",
                        "candidate_score": 0.5,
                        "signals": {"leader_score": 0.4},
                        "rank": 12,
                        "research_tier": "NO_RESEARCH",
                    },
                },
                {
                    "symbol": "600001.SH",
                    "rating": "WATCH",
                    "action": "WAIT_FOR_CONFIRMATION",
                    "gate": {"passed": True, "reason": "SIGNAL_PASS", "research_tier": "DEEP_RESEARCH"},
                    "chairman": {"source": "llm"},
                },
            ],
        }
    ]
    cycles = [
        {"as_of": "2026-08-25", "candidate_count": 60, "research_count": 20, "cycle_id": "a"},
        {"as_of": "2026-08-25", "candidate_count": 60, "research_count": 20, "cycle_id": "b"},
    ]
    cov = analyze_calendar_coverage(
        start=date(2026, 8, 24),
        end=date(2026, 8, 25),
        reports=reports,
        cycles=cycles,
    )
    assert cov["calendar_days"] == 2
    assert cov["active_days"] == 1
    assert cov["coverage_pct"] == 50.0
    assert any(d["status"] in {"NOT_RUN", "MISSED_RUN", "SCHEDULED_NOT_STARTED"} for d in cov["per_day"])
    assert any(d["status"] in {"REPORT_OVERWRITTEN", "REPORT_PERSISTED", "HAS_REPORT_OVERWRITTEN"} for d in cov["per_day"])

    gs = extract_gate_skip_cases(reports)
    assert gs["n_gate_skip"] == 1
    assert gs["category_counts"]["DEEP_BUDGET"] == 1
    assert gs["cases"][0]["reason_code"] == "DEEP_BUDGET"

    deep = extract_deep_budget_cases(reports, max_deep=10)
    assert deep["n_deep_budget"] == 1
    assert deep["cases"][0]["entered_full_ai_council"] is False
    assert deep["n_high_quality_blocked"] >= 1

    council = analyze_council_breakdown(reports)
    assert council["full_ai_council"] == 1
    assert council["gate_skip"] == 1
    assert council["watch"] == 1


def test_execution_chain_autostart_false():
    chain = analyze_execution_chain({"agent": {"autostart": False, "interval_sec": 1800}})
    assert chain["agent.autostart"] is False
    assert chain["auto_runs_daily_without_manual_start"] is False
    assert any(e["id"] == "api_agent_start" for e in chain["real_entrypoints"])
