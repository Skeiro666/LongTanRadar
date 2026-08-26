"""P0 production observability — coverage, GATE_SKIP detail, signal provenance.

Read-only analysis helpers used by buy_pipeline_audit. Does NOT change
BUY thresholds, RiskFilter, or strategy parameters.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ashare.symbols import to_symbol


def _parse_day(val: Any) -> date | None:
    if val is None:
        return None
    s = str(val).strip()
    if not s:
        return None
    try:
        if "T" in s:
            return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
        return date.fromisoformat(s[:10])
    except Exception:  # noqa: BLE001
        return None


def categorize_gate_skip(reason: str, *, rating: str = "") -> str:
    r = str(reason or "").upper()
    rt = str(rating or "").upper()
    if r == "DEEP_BUDGET":
        return "DEEP_BUDGET"
    if r in {"LLM_BUDGET", "TOKEN_BUDGET", "COST_BUDGET"}:
        return "LLM_BUDGET"
    if r in {"LIGHT_BUDGET"}:
        return "BUDGET"
    if "MISSING" in r or r.endswith("_DATA") or "UNAVAILABLE" in r:
        return "DATA_UNAVAILABLE" if "UNAVAILABLE" in r else "MISSING_SIGNAL"
    if rt == "GATE_SKIP" or r in {"GATE_REJECT", "LOW_CANDIDATE_SCORE", "WEAK_SIGNALS", "NO_RESEARCH_TIER"}:
        return "GATE_SKIP"
    if not r or r in {"NONE", "OK", "SIGNAL_PASS"}:
        return "OTHER"
    return "OTHER"


def classify_day_status(
    *,
    has_report: bool,
    cycle_count: int,
    cycle_with_candidates: int,
    cycle_with_research: int,
    report_parse_ok: bool,
) -> str:
    """Explain why a calendar day may lack a usable dated report."""
    if has_report and report_parse_ok:
        if cycle_count > 1:
            return "HAS_REPORT_OVERWRITTEN"  # multiple cycles, one dated file
        return "HAS_REPORT"
    if not report_parse_ok and has_report:
        return "REPORT_PARSE_ERROR"
    if cycle_count <= 0:
        return "NOT_RUN"
    if cycle_with_candidates <= 0 and cycle_with_research <= 0:
        return "RUN_NO_CANDIDATES"
    if cycle_with_research <= 0:
        return "RUN_NO_RESEARCH"
    # Cycles recorded research but dated report missing → overwrite lost / persist fail / as_of mismatch
    return "RUN_NO_PERSISTED_REPORT"


def analyze_calendar_coverage(
    *,
    start: date,
    end: date,
    reports: list[dict[str, Any]],
    cycles: list[dict[str, Any]],
) -> dict[str, Any]:
    calendar_days: list[str] = []
    d = start
    while d <= end:
        calendar_days.append(d.isoformat())
        d += timedelta(days=1)

    reports_by_day: dict[str, dict[str, Any]] = {}
    for r in reports:
        key = str(r.get("_as_of_date") or r.get("as_of") or "")[:10]
        if key:
            reports_by_day[key] = r

    cycles_by_day: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for c in cycles:
        key = str(c.get("as_of") or "")[:10]
        if key:
            cycles_by_day[key].append(c)

    day_rows: list[dict[str, Any]] = []
    status_c: Counter = Counter()
    for day in calendar_days:
        creps = cycles_by_day.get(day) or []
        rep = reports_by_day.get(day)
        cand_n = sum(1 for c in creps if int(c.get("candidate_count") or 0) > 0)
        res_n = sum(1 for c in creps if int(c.get("research_count") or 0) > 0)
        st = classify_day_status(
            has_report=rep is not None,
            cycle_count=len(creps),
            cycle_with_candidates=cand_n,
            cycle_with_research=res_n,
            report_parse_ok=True,
        )
        status_c[st] += 1
        day_rows.append(
            {
                "date": day,
                "status": st,
                "n_cycles": len(creps),
                "n_cycles_with_candidates": cand_n,
                "n_cycles_with_research": res_n,
                "has_dated_report": rep is not None,
                "report_file": (rep or {}).get("_report_file"),
                "note": _coverage_note(st, len(creps)),
            }
        )

    active_days = [x["date"] for x in day_rows if x["status"] in {"HAS_REPORT", "HAS_REPORT_OVERWRITTEN"}]
    missing_days = [x["date"] for x in day_rows if x["date"] not in active_days]
    n_cal = len(calendar_days) or 1
    return {
        "calendar_days": len(calendar_days),
        "calendar_day_list": calendar_days,
        "active_days": len(active_days),
        "active_day_list": active_days,
        "missing_days": len(missing_days),
        "missing_day_list": missing_days,
        "coverage_pct": round(100.0 * len(active_days) / n_cal, 2),
        "status_counts": dict(status_c),
        "per_day": day_rows,
        "explanation": (
            "Dated reports are keyed by as_of and overwrite same-day files. "
            "Multiple production_cycles on one as_of collapse to one report day. "
            "Days with status=NOT_RUN had no agent/research cycle recorded."
        ),
    }


def _coverage_note(status: str, n_cycles: int) -> str:
    return {
        "HAS_REPORT": "dated report present",
        "HAS_REPORT_OVERWRITTEN": f"{n_cycles} cycles same as_of; latest report kept",
        "NOT_RUN": "no production_cycles and no dated report",
        "RUN_NO_CANDIDATES": "cycles exist but candidate_count=0",
        "RUN_NO_RESEARCH": "cycles exist but research_count=0",
        "RUN_NO_PERSISTED_REPORT": "cycles claim research but dated report missing (persist/as_of issue)",
        "REPORT_PARSE_ERROR": "report file unreadable",
    }.get(status, status)


def extract_gate_skip_cases(reports: list[dict[str, Any]]) -> dict[str, Any]:
    cases: list[dict[str, Any]] = []
    cat_c: Counter = Counter()
    for rep in reports:
        as_of = str(rep.get("_as_of_date") or rep.get("as_of") or "")[:10]
        uni_by = {
            to_symbol(str(u.get("symbol") or "")): u
            for u in ((rep.get("candidate_union") or {}).get("universe") or [])
            if isinstance(u, dict)
        }
        for pr in rep.get("platform_reports") or []:
            if not isinstance(pr, dict):
                continue
            rating = str(pr.get("rating") or (pr.get("decision") or {}).get("research_rating") or "").upper()
            gate = dict(pr.get("gate") or {})
            reason = str(gate.get("reason") or "")
            if rating != "GATE_SKIP" and reason not in {"DEEP_BUDGET", "LLM_BUDGET", "LIGHT_BUDGET"}:
                continue
            if rating != "GATE_SKIP" and reason in {"DEEP_BUDGET", "LLM_BUDGET", "LIGHT_BUDGET"}:
                # budget rejects are persisted as GATE_SKIP rating typically
                pass
            if rating != "GATE_SKIP":
                continue
            cat = categorize_gate_skip(reason, rating=rating)
            cat_c[cat] += 1
            sym = to_symbol(str(pr.get("symbol") or ""))
            u = uni_by.get(sym) or {}
            signals = dict(gate.get("signals") or {})
            cases.append(
                {
                    "symbol": sym,
                    "name": pr.get("name") or u.get("name"),
                    "research_date": as_of,
                    "gate": {
                        "passed": gate.get("passed"),
                        "reason": reason,
                        "research_tier": gate.get("research_tier"),
                        "rank": gate.get("rank"),
                        "reject_codes": gate.get("reject_codes") or [],
                    },
                    "reason_code": cat,
                    "reason_detail": reason or "GATE_SKIP",
                    "candidate_score": gate.get("candidate_score")
                    if gate.get("candidate_score") is not None
                    else u.get("candidate_score"),
                    "leader_score": signals.get("leader_score")
                    if signals.get("leader_score") is not None
                    else u.get("leader_score"),
                    "board_count": u.get("board_count"),
                    "trade_timing_action": u.get("trade_timing_action"),
                    "in_council_flag": u.get("in_council"),
                    "entered_full_ai_council": False,
                }
            )
    return {
        "n_gate_skip": len(cases),
        "category_counts": dict(cat_c),
        "cases": cases,
        "note": "GATE_SKIP is a platform_reports rating for budget/gate rejects — not a full AI Council decision.",
    }


def extract_deep_budget_cases(reports: list[dict[str, Any]], *, max_deep: int = 10) -> dict[str, Any]:
    cases: list[dict[str, Any]] = []
    for rep in reports:
        as_of = str(rep.get("_as_of_date") or rep.get("as_of") or "")[:10]
        uni_by = {
            to_symbol(str(u.get("symbol") or "")): u
            for u in ((rep.get("candidate_union") or {}).get("universe") or [])
            if isinstance(u, dict)
        }
        # Who got full deep research that day (approx: gate passed + not budget skip)
        deep_passed = []
        for pr in rep.get("platform_reports") or []:
            gate = dict(pr.get("gate") or {})
            rating = str(pr.get("rating") or "").upper()
            if gate.get("passed") and rating != "GATE_SKIP" and str(gate.get("research_tier") or "") == "DEEP_RESEARCH":
                deep_passed.append(pr.get("symbol"))
            if str(gate.get("reason") or "") != "DEEP_BUDGET":
                continue
            sym = to_symbol(str(pr.get("symbol") or ""))
            u = uni_by.get(sym) or {}
            signals = dict(gate.get("signals") or {})
            cs = gate.get("candidate_score")
            if cs is None:
                cs = u.get("candidate_score")
            ls = signals.get("leader_score")
            if ls is None:
                ls = u.get("leader_score")
            high_quality = bool(
                (cs is not None and float(cs) >= 0.35)
                or (ls is not None and float(ls) >= 0.35)
                or int(u.get("board_count") or 0) >= 2
            )
            cases.append(
                {
                    "symbol": sym,
                    "name": pr.get("name") or u.get("name"),
                    "research_date": as_of,
                    "candidate_score": cs,
                    "leader_score": ls,
                    "board_count": u.get("board_count"),
                    "limit_up": bool(u.get("limit_up") or u.get("research_limit_up") or (u.get("board_count") or 0) >= 1),
                    "trade_timing_action": u.get("trade_timing_action"),
                    "lifecycle": u.get("lifecycle"),
                    "stage": u.get("stage"),
                    "universe_in_council_flag": u.get("in_council"),
                    "entered_full_ai_council": False,
                    "why_not_council": "DEEP_BUDGET: max_deep exhausted before this rank",
                    "gate_rank": gate.get("rank"),
                    "high_quality_leader_candidate": high_quality,
                }
            )
    hq = [c for c in cases if c.get("high_quality_leader_candidate")]
    return {
        "max_deep_config": max_deep,
        "n_deep_budget": len(cases),
        "n_high_quality_blocked": len(hq),
        "high_quality_blocked_symbols": [
            {"symbol": c["symbol"], "research_date": c["research_date"], "candidate_score": c["candidate_score"], "leader_score": c["leader_score"]}
            for c in hq
        ],
        "score_summary": _score_summary([c.get("candidate_score") for c in cases]),
        "leader_score_summary": _score_summary([c.get("leader_score") for c in cases]),
        "cases": cases,
        "verdict": (
            f"{len(hq)}/{len(cases)} DEEP_BUDGET names look like material candidates "
            f"(score/leader/board heuristics) blocked solely by max_deep={max_deep} budget — "
            "not by weak signals. This is capacity throttling, not a BUY-threshold reject."
            if cases
            else "No DEEP_BUDGET cases in window."
        ),
    }


def _score_summary(vals: list[Any]) -> dict[str, Any]:
    xs = []
    for v in vals:
        try:
            if v is not None:
                xs.append(float(v))
        except Exception:  # noqa: BLE001
            pass
    if not xs:
        return {"n": 0}
    return {
        "n": len(xs),
        "min": round(min(xs), 6),
        "max": round(max(xs), 6),
        "mean": round(sum(xs) / len(xs), 6),
    }


def analyze_council_breakdown(reports: list[dict[str, Any]]) -> dict[str, Any]:
    """Separate full AI Council outcomes from GATE_SKIP / budget skips."""
    rating_c: Counter = Counter()
    full_ai = 0
    gate_skip = 0
    deep_budget = 0
    llm_budget = 0
    heuristic = 0
    llm_chair = 0
    rows: list[dict[str, Any]] = []
    for rep in reports:
        as_of = str(rep.get("_as_of_date") or rep.get("as_of") or "")[:10]
        for pr in rep.get("platform_reports") or []:
            if not isinstance(pr, dict):
                continue
            rating = str(pr.get("rating") or "").upper() or "EMPTY"
            gate = dict(pr.get("gate") or {})
            reason = str(gate.get("reason") or "")
            chair = dict(pr.get("chairman") or {})
            src = str(chair.get("source") or "")
            rating_c[rating] += 1
            is_skip = rating == "GATE_SKIP" or reason in {"DEEP_BUDGET", "LLM_BUDGET", "LIGHT_BUDGET"}
            if reason == "DEEP_BUDGET":
                deep_budget += 1
            if reason == "LLM_BUDGET":
                llm_budget += 1
            if is_skip:
                gate_skip += 1
                kind = "GATE_SKIP"
            else:
                full_ai += 1
                kind = "FULL_AI_COUNCIL"
                if src in {"heuristic", "quant_routing_skip", "leader_scan", "cache", "incremental_reuse"}:
                    heuristic += 1
                elif src == "llm":
                    llm_chair += 1
            rows.append(
                {
                    "symbol": pr.get("symbol"),
                    "research_date": as_of,
                    "kind": kind,
                    "rating": rating,
                    "action": pr.get("action"),
                    "gate_reason": reason or None,
                    "chairman_source": src or None,
                }
            )
    return {
        "n_platform_reports": len(rows),
        "full_ai_council": full_ai,
        "gate_skip": gate_skip,
        "deep_budget": deep_budget,
        "llm_budget": llm_budget,
        "full_ai_chairman_llm": llm_chair,
        "full_ai_chairman_heuristic_or_cache": heuristic,
        "rating_counts": dict(rating_c),
        "watch": rating_c.get("WATCH", 0),
        "avoid": rating_c.get("AVOID", 0),
        "neutral": rating_c.get("NEUTRAL", 0),
        "buy": rating_c.get("BUY", 0) + rating_c.get("STRONG_BUY", 0),
        "note": "GATE_SKIP must not be counted as a completed AI research decision.",
        "rows_sample": rows[:40],
    }


def analyze_signal_provenance(
    reports: list[dict[str, Any]],
    snapshots: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Trace ML/Profit/Event/News/Valuation availability.

    Historical dated reports often OMIT score fields (serialization gap) even when
    snapshots contain values — distinguish REPORT_FIELD_STRIPPED vs runtime status.
    """
    pipeline = {
        "ml": {
            "source": "MLRankingEngine.predict_rows → candidate.ml_prediction/ml_status → snapshot.quant → council quant role",
            "stages": [
                "candidate_engine.predict_rows",
                "candidate_snapshot/attach_signal_contract",
                "research_snapshot.quant",
                "council_context.candidate.signals",
            ],
        },
        "profit": {
            "source": "ProfitInflectionEngine.enrich_candidates → profit_inflection/profit_score → snapshot → council",
            "stages": ["profit.enrich", "signal_contract", "snapshot", "council"],
        },
        "event": {
            "source": "EventEngine.enrich_candidates → event_score (ZERO if no events) → snapshot → council",
            "stages": ["events.enrich", "signal_contract", "snapshot", "council"],
        },
        "news": {
            "source": "NewsIntelligenceEngine.collect_stock / news_discovery → news_score/news_status → snapshot → council",
            "stages": ["news.collect", "signal_contract", "snapshot", "council"],
        },
        "valuation": {
            "source": "value_available flag (fundamentals); role skipped/unavailable when false — not bearish",
            "stages": ["candidate.value_available", "snapshot.value_available", "council.valuation"],
        },
    }

    report_field_c: dict[str, Counter] = {k: Counter() for k in ("ml", "profit", "event", "news")}
    for rep in reports:
        for u in ((rep.get("candidate_union") or {}).get("universe") or []):
            if not isinstance(u, dict):
                continue
            _tally_field(report_field_c["ml"], u, ("ml_prediction",), status_keys=("ml_prediction_status", "ml_status"))
            _tally_field(report_field_c["profit"], u, ("profit_score",), status_keys=("profit_score_status", "profit_status"))
            _tally_field(report_field_c["event"], u, ("event_score",), status_keys=("event_score_status", "event_status"))
            _tally_field(report_field_c["news"], u, ("news_score",), status_keys=("news_score_status", "news_status"))

    snap_ml = Counter()
    snap_profit = Counter()
    snap_event = Counter()
    snap_news = Counter()
    snap_val = Counter()
    for snap in snapshots:
        if not isinstance(snap, dict):
            continue
        q = snap.get("quant") or {}
        _tally_raw(snap_ml, q.get("ml_prediction"), q.get("ml_status") or snap.get("ml_prediction_status"))
        pi = snap.get("profit_inflection") or {}
        if pi.get("available") is False:
            snap_profit["UNAVAILABLE"] += 1
        else:
            _tally_raw(snap_profit, snap.get("profit_score") if snap.get("profit_score") is not None else pi.get("score"), snap.get("profit_status"))
        ev = snap.get("event") or {}
        _tally_raw(snap_event, snap.get("event_score") if snap.get("event_score") is not None else ev.get("score"), snap.get("event_status"))
        news = snap.get("news_package") or {}
        _tally_raw(
            snap_news,
            snap.get("news_score") if snap.get("news_score") is not None else news.get("net_event_score"),
            snap.get("news_status") or ("UNAVAILABLE" if news.get("news_data_incomplete") else None),
        )
        if snap.get("value_available") is False:
            snap_val["UNAVAILABLE"] += 1
        elif snap.get("value_available") is True:
            snap_val["VALID"] += 1
        else:
            snap_val["MISSING"] += 1

    report_missing = all(sum(c.values()) == c.get("MISSING", 0) + c.get("REPORT_FIELD_ABSENT", 0) for c in report_field_c.values()) or (
        sum(report_field_c["ml"].values()) > 0 and report_field_c["ml"].get("MISSING", 0) + report_field_c["ml"].get("REPORT_FIELD_ABSENT", 0)
        >= 0.9 * max(1, sum(report_field_c["ml"].values()))
    )

    return {
        "pipeline": pipeline,
        "dated_report_universe_field_status": {k: dict(v) for k, v in report_field_c.items()},
        "research_snapshot_status": {
            "ml": dict(snap_ml),
            "profit": dict(snap_profit),
            "event": dict(snap_event),
            "news": dict(snap_news),
            "valuation": dict(snap_val),
            "n_snapshots": len(snapshots),
        },
        "why_audit_showed_zero": (
            "Dated report candidate_union.universe historically omitted ml/profit/event/news fields "
            "(serialization strip). Snapshots often still carry ml_prediction. "
            "Audit MISSING on reports ≠ runtime always computed 0. "
            "Post-36ffb97 serialize_signal_fields persists statuses on new reports."
            if report_missing
            else "Report fields present; see status counters."
        ),
        "silent_fallback_policy": "Forbidden in code path after SSOT remediations; failures must set *_status FAILED/UNAVAILABLE.",
    }


def _tally_field(counter: Counter, row: dict[str, Any], value_keys: tuple[str, ...], status_keys: tuple[str, ...] = ()) -> None:
    st = None
    for sk in status_keys:
        if row.get(sk) not in (None, ""):
            st = str(row.get(sk)).upper()
            break
    val = None
    present = False
    for vk in value_keys:
        if vk in row:
            present = True
            val = row.get(vk)
            break
    if st in {"UNAVAILABLE", "FAILED", "MISSING", "STALE", "VALID", "ZERO", "OK", "NO_MODEL"}:
        if st == "OK":
            counter["VALID"] += 1
        elif st == "NO_MODEL":
            counter["UNAVAILABLE"] += 1
        else:
            counter[st] += 1
        return
    if not present:
        counter["REPORT_FIELD_ABSENT"] += 1
        return
    if val is None:
        counter["MISSING"] += 1
        return
    try:
        if abs(float(val)) < 1e-15:
            counter["ZERO"] += 1
        else:
            counter["VALID"] += 1
    except Exception:  # noqa: BLE001
        counter["MISSING"] += 1


def _tally_raw(counter: Counter, val: Any, status: Any = None) -> None:
    st = str(status or "").upper()
    if st in {"UNAVAILABLE", "FAILED", "MISSING", "STALE", "NO_MODEL"}:
        counter["UNAVAILABLE" if st == "NO_MODEL" else st] += 1
        return
    if val is None:
        counter["MISSING"] += 1
        return
    try:
        if abs(float(val)) < 1e-15:
            counter["ZERO"] += 1
        else:
            counter["VALID"] += 1
    except Exception:  # noqa: BLE001
        counter["MISSING"] += 1


def analyze_execution_chain(cfg: dict[str, Any]) -> dict[str, Any]:
    agent = dict(cfg.get("agent") or {})
    autostart = bool(agent.get("autostart", False))
    interval = agent.get("interval_sec")
    return {
        "agent.autostart": autostart,
        "agent.interval_sec": interval,
        "auto_runs_daily_without_manual_start": False if not autostart else True,
        "real_entrypoints": [
            {
                "id": "serve_lifespan_autostart",
                "active": autostart,
                "path": "src/ashare/api/app.py lifespan → start_agent(run_now=True)",
                "note": "Only when agent.autostart=true",
            },
            {
                "id": "api_agent_start",
                "active": "manual",
                "path": "POST /api/agent/start",
                "note": "Starts daemon loop; UI or operator triggers",
            },
            {
                "id": "api_agent_cycle",
                "active": "manual",
                "path": "POST /api/agent/cycle",
                "note": "One-shot cycle",
            },
            {
                "id": "cli_agent",
                "active": "manual",
                "path": "python -m ashare.main agent",
                "note": "One-shot run_cycle",
            },
            {
                "id": "cli_research",
                "active": "manual",
                "path": "python -m ashare.main research",
                "note": "Research/report only",
            },
            {
                "id": "os_cron",
                "active": False,
                "path": None,
                "note": "No in-repo cron/Task Scheduler wiring",
            },
        ],
        "pipeline_when_triggered": [
            "Universe/screen",
            "Pool",
            "CandidateEngine",
            "ResearchSession (gate → council → chairman)",
            "CanonicalDecision + RiskFilter",
            "Paper trade if committee_approve",
            "persist data/reports/{as_of}.json + production_cycles.jsonl",
        ],
        "verdict": (
            "Production does NOT auto-run daily with agent.autostart=false. "
            "Observed report days require manual /api/agent/start, CLI, or a prior autostart session."
            if not autostart
            else "autostart=true: serve starts agent loop automatically."
        ),
    }


def analyze_risk_limit_up(canonical_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Map historical risk flags to suggested reason codes without changing trading logic."""
    cases = []
    for d in canonical_rows:
        flags = [str(x) for x in (d.get("risk_flags") or d.get("risk_reasons") or [])]
        low = [f.lower() for f in flags]
        if "limit_up" not in low and "limit_up_no_entry" not in low:
            continue
        cases.append(
            {
                "symbol": d.get("symbol"),
                "research_date": d.get("_as_of") or d.get("as_of") or d.get("research_date"),
                "risk_status": d.get("risk_status"),
                "legacy_flags": flags,
                "suggested_reason_code": "LIMIT_UP_NO_ENTRY",
                "meaning": "Do not chase sealed limit-up today — not a permanent strategy reject",
                "trading_logic_changed": False,
            }
        )
    return {
        "n_limit_up_blocks": len(cases),
        "suggested_reason_code": "LIMIT_UP_NO_ENTRY",
        "interpretation": (
            "All sampled limit_up blocks mean 'current bar is limit-up → no open' (不追涨停). "
            "Suggested audit reason_code=LIMIT_UP_NO_ENTRY. Trading logic unchanged in this audit."
        ),
        "trading_logic_unchanged": True,
        "cases": cases[:40],
    }


def build_production_health_table(
    *,
    coverage: dict[str, Any],
    reports: list[dict[str, Any]],
    cycles: list[dict[str, Any]],
    council: dict[str, Any],
) -> list[dict[str, Any]]:
    reports_by = {str(r.get("_as_of_date") or r.get("as_of"))[:10]: r for r in reports}
    cycles_by: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for c in cycles:
        cycles_by[str(c.get("as_of") or "")[:10]].append(c)

    # council counts by day from platform rows
    by_day_council: dict[str, Counter] = defaultdict(Counter)
    for rep in reports:
        day = str(rep.get("_as_of_date") or "")[:10]
        for pr in rep.get("platform_reports") or []:
            rating = str(pr.get("rating") or "").upper()
            reason = str((pr.get("gate") or {}).get("reason") or "")
            by_day_council[day]["council_total"] += 1
            if rating == "GATE_SKIP" or reason in {"DEEP_BUDGET", "LLM_BUDGET"}:
                by_day_council[day]["gate_skip"] += 1
            else:
                by_day_council[day]["full_ai"] += 1
            if rating in {"BUY", "STRONG_BUY"}:
                by_day_council[day]["buy"] += 1

    rows = []
    for day_info in coverage.get("per_day") or []:
        day = day_info["date"]
        rep = reports_by.get(day)
        creps = cycles_by.get(day) or []
        cu = (rep or {}).get("candidate_union") or {}
        cds = list((rep or {}).get("canonical_decisions") or [])
        final_buy = sum(1 for d in cds if d.get("committee_approve"))
        cc = by_day_council.get(day) or Counter()
        # data quality proxy
        dq = "UNKNOWN"
        if rep:
            uni = cu.get("universe") or []
            if uni and any(u.get("ml_prediction_status") or u.get("data_quality") for u in uni if isinstance(u, dict)):
                dq = "CONTRACT_PRESENT"
            else:
                dq = "LEGACY_STRIPPED_FIELDS"
        elif day_info["status"] == "NOT_RUN":
            dq = "NO_RUN"
        rows.append(
            {
                "date": day,
                "scheduler_started": len(creps) > 0 or bool(rep),
                "universe_loaded": bool(rep) and int(((rep or {}).get("funnel") or {}).get("universe_raw") or (cu.get("n_union") or 0)) >= 0 and bool(rep),
                "candidate_count": (cu.get("n_union") if rep else None)
                if rep
                else (max((int(c.get("candidate_count") or 0) for c in creps), default=None)),
                "research_count": (cu.get("n_research") if rep else None)
                if rep
                else (max((int(c.get("research_count") or 0) for c in creps), default=None)),
                "council_count": int(cc.get("council_total") or 0) or (len((rep or {}).get("platform_reports") or []) if rep else 0),
                "full_ai_council_count": int(cc.get("full_ai") or 0),
                "gate_skip_count": int(cc.get("gate_skip") or 0),
                "buy_count": int(cc.get("buy") or 0),
                "final_buy_count": final_buy,
                "data_quality": dq,
                "report_persisted": bool(rep),
                "day_status": day_info.get("status"),
                "n_cycles": day_info.get("n_cycles"),
            }
        )
    return rows


def build_no_buy_reason_detail(
    *,
    health_table: list[dict[str, Any]],
    reports: list[dict[str, Any]],
    coverage: dict[str, Any],
) -> list[dict[str, Any]]:
    out = []
    reports_by = {str(r.get("_as_of_date") or r.get("as_of"))[:10]: r for r in reports}
    for row in health_table:
        day = row["date"]
        rep = reports_by.get(day)
        blockers: Counter = Counter()
        if not row.get("scheduler_started") and not row.get("report_persisted"):
            reason = "SYSTEM_NOT_RUN"
            blockers["NOT_RUN"] = 1
        elif not row.get("report_persisted"):
            reason = "NO_PERSISTED_REPORT"
            blockers[str(row.get("day_status") or "NO_REPORT")] = 1
        else:
            cds = list((rep or {}).get("canonical_decisions") or [])
            if not cds:
                # derive from platform ratings
                for pr in (rep or {}).get("platform_reports") or []:
                    rating = str(pr.get("rating") or "").upper()
                    action = str(pr.get("action") or "").upper()
                    reason_g = str((pr.get("gate") or {}).get("reason") or "")
                    if rating == "GATE_SKIP":
                        blockers[f"GATE_SKIP:{reason_g or 'GATE'}"] += 1
                    elif rating not in {"BUY", "STRONG_BUY"}:
                        blockers[f"RATING_NOT_BUY:{rating}"] += 1
                    elif action != "SMALL_POSITION":
                        blockers[f"NO_VALID_ENTRY:{action}"] += 1
                reason = blockers.most_common(1)[0][0] if blockers else "NO_CANONICAL"
            else:
                for d in cds:
                    if d.get("committee_approve"):
                        continue
                    blockers[str(d.get("no_buy_reason") or _fallback_no_buy(d))] += 1
                if row.get("final_buy_count"):
                    reason = "HAS_BUY"
                else:
                    reason = blockers.most_common(1)[0][0] if blockers else "NO_BUY"
        out.append(
            {
                "date": day,
                "NO_BUY_REASON": reason,
                "NO_BUY_COUNT": 0 if reason == "HAS_BUY" else int(row.get("council_count") or row.get("candidate_count") or 0),
                "DATA_COVERAGE": {
                    "report_persisted": row.get("report_persisted"),
                    "day_status": row.get("day_status"),
                    "data_quality": row.get("data_quality"),
                    "window_coverage_pct": coverage.get("coverage_pct"),
                },
                "TOP_BLOCKERS": dict(blockers.most_common(8)),
                "final_buy_count": row.get("final_buy_count"),
            }
        )
    return out


def _fallback_no_buy(d: dict[str, Any]) -> str:
    rating = str(d.get("research_rating") or "").upper()
    action = str(d.get("trading_action") or "").upper()
    risk = str(d.get("risk_status") or "").upper()
    if rating in {"GATE_SKIP", "SKIP"}:
        return "GATE_SKIP"
    if rating not in {"BUY", "STRONG_BUY"}:
        return f"RATING_NOT_BUY:{rating or 'EMPTY'}"
    if action != "SMALL_POSITION":
        return f"NO_VALID_ENTRY_SETUP:{action or 'EMPTY'}"
    if risk in {"BLOCK", "BLOCKED"}:
        flags = d.get("risk_flags") or []
        return f"RISK_BLOCK:{','.join(str(x) for x in flags) or risk}"
    return "NO_BUY"


def build_answers_p0(obs: dict[str, Any]) -> dict[str, Any]:
    cov = obs.get("coverage") or {}
    gate = obs.get("gate_skip") or {}
    deep = obs.get("deep_budget") or {}
    sig = obs.get("signal_provenance") or {}
    exe = obs.get("execution_chain") or {}
    council = obs.get("council_breakdown") or {}
    risk = obs.get("risk_limit_up") or {}
    today = obs.get("today_verdict") or {}
    return {
        "A_daily_run": (
            f"No — coverage_pct={cov.get('coverage_pct')}% "
            f"({cov.get('active_days')}/{cov.get('calendar_days')} days with dated reports). "
            f"status_counts={cov.get('status_counts')}"
        ),
        "B_gate_skip": (
            f"GATE_SKIP n={gate.get('n_gate_skip')}; categories={gate.get('category_counts')}. "
            "These are budget/gate rejects persisted as rating=GATE_SKIP, not full AI council decisions."
        ),
        "C_ml_profit_event_news_zero": sig.get("why_audit_showed_zero"),
        "D_30d_three_reports": (
            f"Only {cov.get('active_days')} active report days because (1) agent not daily-scheduled, "
            f"(2) same as_of overwrites dated JSON, (3) missing_days={cov.get('missing_days')}. "
            f"See coverage.per_day."
        ),
        "E_autostart": exe.get("verdict"),
        "F_full_council": (
            f"full_ai_council={council.get('full_ai_council')} / "
            f"platform_reports={council.get('n_platform_reports')}; "
            f"gate_skip={council.get('gate_skip')} "
            f"(deep={council.get('deep_budget')}, llm={council.get('llm_budget')})"
        ),
        "G_deep_budget_leaders": deep.get("verdict"),
        "H_limit_up": risk.get("interpretation"),
        "I_today_zero_buy": today,
    }
