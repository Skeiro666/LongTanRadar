"""7-day BUY Pipeline Audit — read-only, no threshold / prompt / RiskFilter changes."""

from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ashare.config_loaders import load_yaml_config
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


def _pct(n: int, d: int) -> float:
    return round(100.0 * n / d, 2) if d else 0.0


def _quantile(vals: list[float], q: float) -> float | None:
    if not vals:
        return None
    xs = sorted(float(v) for v in vals)
    if len(xs) == 1:
        return xs[0]
    pos = (len(xs) - 1) * q
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return xs[lo]
    return xs[lo] * (hi - pos) + xs[hi] * (pos - lo)


def _score_dist(vals: list[float]) -> dict[str, Any]:
    if not vals:
        return {"n": 0}
    return {
        "n": len(vals),
        "min": round(min(vals), 6),
        "p25": round(_quantile(vals, 0.25) or 0.0, 6),
        "p50": round(_quantile(vals, 0.50) or 0.0, 6),
        "p75": round(_quantile(vals, 0.75) or 0.0, 6),
        "p90": round(_quantile(vals, 0.90) or 0.0, 6),
        "p95": round(_quantile(vals, 0.95) or 0.0, 6),
        "max": round(max(vals), 6),
        "mean": round(sum(vals) / len(vals), 6),
    }


def _load_json(path: Path) -> dict[str, Any] | list[Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except Exception:  # noqa: BLE001
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def _council_roles(council: Any) -> dict[str, dict[str, Any]]:
    if isinstance(council, dict):
        return {
            str(k): v
            for k, v in council.items()
            if isinstance(v, dict) and not str(k).startswith("_")
        }
    if isinstance(council, list):
        out: dict[str, dict[str, Any]] = {}
        for item in council:
            if not isinstance(item, dict):
                continue
            rid = str(item.get("role") or item.get("id") or "")
            if rid:
                out[rid] = item
        return out
    return {}


def _root(cfg: dict[str, Any]) -> Path:
    return Path(cfg.get("_root") or Path.cwd())


def _in_window(d: date | None, start: date, end: date) -> bool:
    return d is not None and start <= d <= end


def load_dated_reports(root: Path, start: date, end: date) -> list[dict[str, Any]]:
    reports_dir = root / "data" / "reports"
    out: list[dict[str, Any]] = []
    if not reports_dir.exists():
        return out
    for p in sorted(reports_dir.glob("*.json")):
        if p.name in {"latest.json"}:
            continue
        raw = _load_json(p)
        if not isinstance(raw, dict):
            continue
        as_of = _parse_day(raw.get("as_of") or p.stem)
        if not _in_window(as_of, start, end):
            continue
        raw["_report_file"] = p.name
        raw["_as_of_date"] = as_of.isoformat() if as_of else None
        out.append(raw)
    # Deduplicate by as_of (keep latest file order)
    by_day: dict[str, dict[str, Any]] = {}
    for r in out:
        key = str(r.get("_as_of_date") or r.get("as_of") or r.get("_report_file"))
        by_day[key] = r
    return list(by_day.values())


def load_snapshots(root: Path, start: date, end: date) -> list[dict[str, Any]]:
    snap_dir = root / "data" / "research_snapshots"
    out: list[dict[str, Any]] = []
    if not snap_dir.exists():
        return out
    for p in snap_dir.glob("R*.json"):
        raw = _load_json(p)
        if not isinstance(raw, dict):
            continue
        d = _parse_day(raw.get("research_time") or raw.get("snapshot_time") or raw.get("as_of"))
        if not _in_window(d, start, end):
            continue
        raw["_snapshot_file"] = p.name
        raw["_day"] = d.isoformat() if d else None
        out.append(raw)
    return out


def _universe_rows(report: dict[str, Any]) -> list[dict[str, Any]]:
    cu = report.get("candidate_union") or {}
    rows = list(cu.get("universe") or [])
    if not rows:
        rows = list(report.get("pool") or []) if isinstance(report.get("pool"), list) else []
    return [r for r in rows if isinstance(r, dict)]


def _signal_float(row: dict[str, Any], *keys: str) -> float | None:
    for k in keys:
        if row.get(k) is None:
            continue
        try:
            return float(row[k])
        except Exception:  # noqa: BLE001
            continue
    q = row.get("quant") if isinstance(row.get("quant"), dict) else {}
    for k in keys:
        if q.get(k) is None:
            continue
        try:
            return float(q[k])
        except Exception:  # noqa: BLE001
            continue
    return None


def analyze_config(cfg: dict[str, Any]) -> dict[str, Any]:
    ai = dict(cfg.get("ai") or {})
    trading = dict(cfg.get("trading") or {})
    broker = dict(cfg.get("broker") or {})
    agent = dict(cfg.get("agent") or {})
    research = dict(cfg.get("research") or {})
    rc = load_yaml_config(cfg, "research")
    decision = dict(rc.get("decision") or {})
    gate = dict(rc.get("research_gate") or {})
    paper = dict(cfg.get("paper") or {})
    universe = dict(cfg.get("universe") or {})
    screen = dict(universe.get("screen") or {})
    return {
        "trading.mode": trading.get("mode"),
        "broker.mode": broker.get("mode"),
        "agent.autostart": agent.get("autostart"),
        "research.enabled": research.get("enabled", True),
        "ai.enabled": ai.get("enabled"),
        "ai.roundtable": ai.get("roundtable"),
        "ai.roundtable_mode": ai.get("roundtable_mode"),
        "ai.roundtable_sample_every": ai.get("roundtable_sample_every"),
        "ai.roundtable_max_per_day": ai.get("roundtable_max_per_day"),
        "decision.canonical_source": decision.get("canonical_source"),
        "decision.roundtable_controls_trading": decision.get("roundtable_controls_trading"),
        "paper.initial_balance": paper.get("initial_balance"),
        "trading.lot_size": trading.get("lot_size"),
        "universe.screen.max_price": screen.get("max_price"),
        "research_gate": gate,
    }


def _threshold_rejects(
    rows: list[dict[str, Any]],
    gate_cfg: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Count how many universe rows fail each research_gate threshold independently."""
    keys = [
        ("min_candidate_score", ("candidate_score", "score")),
        ("min_leader_score", ("leader_score",)),
        ("min_ml_prediction", ("ml_prediction", "ml_rank_score", "ml_pred")),
        ("min_profit_score", ("profit_score", "profit_gap_score")),
        ("min_event_score", ("event_score",)),
        ("min_news_score", ("news_score", "news_intelligence_score")),
    ]
    out: dict[str, dict[str, Any]] = {}
    n = len(rows)
    for cfg_key, field_keys in keys:
        thr = gate_cfg.get(cfg_key)
        if thr is None:
            continue
        thr_f = float(thr)
        fail = 0
        missing = 0
        below = 0
        zero = 0
        for row in rows:
            # Prefer explicit availability contract when present
            status = None
            for fk in field_keys:
                status = row.get(f"{fk}_status")
                if status:
                    break
            avail = None
            for fk in field_keys:
                if f"{fk}_available" in row:
                    avail = row.get(f"{fk}_available")
                    break
            v = _signal_float(row, *field_keys)
            if status in {"MISSING", "UNAVAILABLE", "FAILED"} or avail is False or v is None:
                missing += 1
                # Soft fields: missing ≠ threshold fail for audit clarity
                continue
            if abs(float(v)) < 1e-15:
                zero += 1
            if v < thr_f:
                below += 1
                fail += 1
        out[cfg_key] = {
            "threshold": thr_f,
            "fail_below_threshold": below,
            "fail": fail,
            "pass": n - fail - missing,
            "missing_or_unavailable": missing,
            "zero_valid": zero,
            "missing_counted_as_fail": 0,
            "fail_rate_pct": _pct(fail, max(n - missing, 1)),
            "missing_rate_pct": _pct(missing, n),
        }
    return out


def _direct_block_reason(d: dict[str, Any]) -> str:
    rating = str(d.get("research_rating") or "").upper()
    action = str(d.get("trading_action") or "").upper()
    risk = str(d.get("risk_status") or "").upper()
    flags = list(d.get("risk_flags") or d.get("risk_reasons") or [])
    approve = bool(d.get("committee_approve"))
    if d.get("no_buy_reason"):
        return str(d.get("no_buy_reason"))
    if approve:
        return "APPROVED"
    if rating in {"GATE_SKIP", "SKIP"} or d.get("gate_passed") is False:
        return f"GATE_REJECT:{flags[0] if flags else 'gate'}"
    if rating not in {"BUY", "STRONG_BUY"}:
        return f"RATING_NOT_BUY:{rating or 'EMPTY'}"
    if action != "SMALL_POSITION":
        return f"NO_VALID_ENTRY_SETUP:{action or 'EMPTY'}"
    if risk in {"BLOCK", "BLOCKED", "FAIL"} or (flags and risk not in {"PASS", "OK", ""}):
        return f"RISK_BLOCK:{','.join(str(x) for x in flags) or risk}"
    if risk == "UNKNOWN":
        return "RISK_UNKNOWN"
    return "UNKNOWN_COMPOUND_GATE"


def run_buy_pipeline_audit(cfg: dict[str, Any], *, days: int = 7) -> dict[str, Any]:
    root = _root(cfg)
    end = date.today()
    # Prefer latest report as_of as end anchor when wall-clock is ahead of data.
    latest = _load_json(root / "data" / "reports" / "latest.json")
    if isinstance(latest, dict) and latest.get("as_of"):
        end_asof = _parse_day(latest.get("as_of"))
        if end_asof:
            end = max(end_asof, end - timedelta(days=1))
    start = end - timedelta(days=max(1, days) - 1)

    rc = load_yaml_config(cfg, "research")
    gate_cfg = dict(rc.get("research_gate") or {})
    config_view = analyze_config(cfg)

    reports = load_dated_reports(root, start, end)
    snapshots = load_snapshots(root, start, end)
    sessions = [
        s
        for s in _load_jsonl(root / "data" / "research_sessions.jsonl")
        if _in_window(_parse_day(s.get("time")), start, end)
    ]
    cycles_raw = _load_jsonl(root / "data" / "production_cycles.jsonl")
    cycles: list[dict[str, Any]] = []
    seen_cycle: set[str] = set()
    for c in cycles_raw:
        d = _parse_day(c.get("as_of") or c.get("recorded_at"))
        if not _in_window(d, start, end):
            continue
        cid = str(c.get("cycle_id") or "")
        if cid and cid in seen_cycle:
            continue
        if cid:
            seen_cycle.add(cid)
        cycles.append(c)

    # --- Funnel aggregates across dated reports ---
    funnel_sum = Counter()
    rating_c = Counter()
    action_c = Counter()
    risk_status_c = Counter()
    risk_flag_c = Counter()
    approve_c = Counter()
    gate_reason_c = Counter()
    buy_ready_c = Counter()
    timing_c = Counter()
    roundtable_runs = 0
    roundtable_details: list[dict[str, Any]] = []
    council_entered = 0
    council_completed = 0
    canonical_rows: list[dict[str, Any]] = []
    platform_rows: list[dict[str, Any]] = []
    candidate_scores: list[float] = []
    leader_scores: list[float] = []
    ml_scores: list[float] = []
    profit_scores: list[float] = []
    event_scores: list[float] = []
    news_scores: list[float] = []
    all_universe_rows: list[dict[str, Any]] = []
    threshold_agg: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for report in reports:
        as_of = str(report.get("_as_of_date") or report.get("as_of") or "")
        screen = report.get("screen") if isinstance(report.get("screen"), dict) else {}
        raw_u = int(screen.get("raw_count") or report.get("universe_size") or 0)
        filtered = int(screen.get("filtered_count") or 0)
        pool = report.get("pool")
        pool_n = len(pool) if isinstance(pool, list) else int(report.get("universe_size") or 0)
        scored = report.get("scored")
        scored_n = len(scored) if isinstance(scored, list) else (int(scored) if isinstance(scored, int) else pool_n)
        cu = report.get("candidate_union") or {}
        uni = list(cu.get("universe") or [])
        research_uni = list(cu.get("research_universe") or [])
        rejected = list(cu.get("rejected") or [])
        uni_n = len(uni) or int(cu.get("n_union") or 0)
        research_n = len(research_uni) or int(cu.get("n_research") or 0)

        funnel_sum["universe_raw"] += raw_u
        funnel_sum["screen_filtered"] += filtered or pool_n
        funnel_sum["pool"] += pool_n
        funnel_sum["scored"] += scored_n
        funnel_sum["candidate_union"] += uni_n
        funnel_sum["research_universe"] += research_n
        funnel_sum["gate_rejected"] += len(rejected)

        for rej in rejected:
            if isinstance(rej, dict):
                reason = str(
                    rej.get("reject_reason")
                    or rej.get("gate_reason")
                    or rej.get("reason")
                    or "REJECT"
                )
                # News-discovery rejects often carry long titles — keep code keys only.
                if len(reason) > 64:
                    reason = reason[:64]
                gate_reason_c[f"union_rejected:{reason}"] += 1
            else:
                gate_reason_c["union_rejected:REJECT"] += 1

        for row in _universe_rows(report):
            all_universe_rows.append(row)
            for lst, keys in (
                (candidate_scores, ("candidate_score", "score")),
                (leader_scores, ("leader_score",)),
                (ml_scores, ("ml_prediction", "ml_rank_score", "ml_pred")),
                (profit_scores, ("profit_score", "profit_gap_score")),
                (event_scores, ("event_score",)),
                (news_scores, ("news_score", "news_intelligence_score")),
            ):
                v = _signal_float(row, *keys)
                if v is not None:
                    lst.append(v)
            ta = str(row.get("trade_timing_action") or "").upper()
            if ta:
                timing_c[ta] += 1
                if ta == "BUY_READY":
                    buy_ready_c["universe_BUY_READY"] += 1

        thr = _threshold_rejects(_universe_rows(report), gate_cfg)
        for k, v in thr.items():
            threshold_agg[k].append(v)

        cds = [d for d in (report.get("canonical_decisions") or []) if isinstance(d, dict)]
        prs = [p for p in (report.get("platform_reports") or []) if isinstance(p, dict)]
        funnel_sum["canonical_decisions"] += len(cds)
        funnel_sum["platform_reports"] += len(prs)
        council_entered += len(prs)
        for pr in prs:
            platform_rows.append({**pr, "_as_of": as_of})
            chair = pr.get("chairman") if isinstance(pr.get("chairman"), dict) else {}
            if chair or pr.get("rating") or pr.get("decision"):
                council_completed += 1
            gate = pr.get("gate") if isinstance(pr.get("gate"), dict) else {}
            if gate.get("passed") is False:
                gate_reason_c[str(gate.get("reason") or "GATE_FAIL")] += 1

        for d in cds:
            d = {**d, "_as_of": as_of, "_report": report.get("_report_file")}
            canonical_rows.append(d)
            rating_c[str(d.get("research_rating") or "EMPTY").upper()] += 1
            action_c[str(d.get("trading_action") or "EMPTY").upper()] += 1
            risk_status_c[str(d.get("risk_status") or "EMPTY").lower()] += 1
            for f in d.get("risk_flags") or []:
                risk_flag_c[str(f)] += 1
            approve_c[bool(d.get("committee_approve"))] += 1
            lt = d.get("leader_timing") if isinstance(d.get("leader_timing"), dict) else {}
            if str(lt.get("trade_timing_action") or "").upper() == "BUY_READY":
                buy_ready_c["canonical_BUY_READY"] += 1

        rt = report.get("roundtable") if isinstance(report.get("roundtable"), dict) else {}
        if rt:
            # Count only if it actually produced roles / summary (ran)
            ran = bool(rt.get("roles") or rt.get("summary") or rt.get("source"))
            if ran and str(rt.get("schedule_reason") or "") not in {"roundtable_disabled", "disabled"}:
                # sampled skip still may have empty roles
                if rt.get("roles") or rt.get("source") not in {None, "skipped"}:
                    roundtable_runs += 1
            roundtable_details.append(
                {
                    "as_of": as_of,
                    "source": rt.get("source"),
                    "controls_trading": rt.get("controls_trading"),
                    "benchmark_only": rt.get("benchmark_only"),
                    "schedule_reason": rt.get("schedule_reason"),
                    "n_roles": len(rt.get("roles") or []),
                }
            )

        alerts = report.get("buy_ready_alerts") or []
        if isinstance(alerts, list):
            buy_ready_c["buy_ready_alerts"] += len(alerts)

    # Snapshot-level council role stats + BUY rated that failed approve
    snap_rating_c = Counter()
    snap_action_c = Counter()
    role_stance_c = Counter()
    role_scores: dict[str, list[float]] = defaultdict(list)
    buy_rated_cases: list[dict[str, Any]] = []
    valuation_unavailable = 0
    bear_negative = 0
    snap_n_with_council = 0

    # Index canonical by symbol+as_of for join
    canon_index: dict[str, dict[str, Any]] = {}
    for d in canonical_rows:
        key = f"{to_symbol(str(d.get('symbol') or ''))}|{d.get('_as_of') or d.get('as_of')}"
        canon_index[key] = d

    for snap in snapshots:
        chair = snap.get("chairman") if isinstance(snap.get("chairman"), dict) else {}
        decision = snap.get("decision") if isinstance(snap.get("decision"), dict) else {}
        rating = str(chair.get("rating") or decision.get("research_rating") or snap.get("rating") or "EMPTY").upper()
        action = str(
            chair.get("trading_action") or decision.get("action") or snap.get("action") or "EMPTY"
        ).upper()
        snap_rating_c[rating] += 1
        snap_action_c[action] += 1
        roles = _council_roles(snap.get("council"))
        if roles:
            snap_n_with_council += 1
        for rid, op in roles.items():
            stance = str(op.get("stance") or "").lower() or "unknown"
            role_stance_c[f"{rid}:{stance}"] += 1
            if rid == "valuation" and str(op.get("status") or "").lower() in {"unavailable", "skipped"}:
                valuation_unavailable += 1
            try:
                sc = float(op.get("score"))
                role_scores[rid].append(sc)
                if rid == "bear" and sc < 0:
                    bear_negative += 1
            except Exception:  # noqa: BLE001
                pass

        if rating in {"BUY", "STRONG_BUY"}:
            sym = to_symbol(str(snap.get("symbol") or ""))
            day = snap.get("_day")
            market = snap.get("market") if isinstance(snap.get("market"), dict) else {}
            quant = snap.get("quant") if isinstance(snap.get("quant"), dict) else {}
            # Prefer exact as_of join; do not fall back to unrelated report days.
            joined = canon_index.get(f"{sym}|{day}")
            risk_status = None
            risk_flags: list[Any] = []
            approve = False
            if joined:
                risk_status = joined.get("risk_status")
                risk_flags = list(joined.get("risk_flags") or [])
                approve = bool(joined.get("committee_approve"))
            else:
                # Reconstruct compound gate from snapshot itself (audit-only).
                limit_up = bool(market.get("limit_up") or quant.get("limit_up") or snap.get("limit_up"))
                if limit_up:
                    risk_status = "blocked"
                    risk_flags = ["limit_up"]
                else:
                    risk_status = "unknown_no_canonical_row"
                    risk_flags = []
                approve = (
                    rating in {"BUY", "STRONG_BUY"}
                    and action == "SMALL_POSITION"
                    and not limit_up
                )
            synth = {
                "research_rating": rating,
                "trading_action": action,
                "committee_approve": approve,
                "risk_status": risk_status,
                "risk_flags": risk_flags,
                "gate_passed": True,
            }
            case = {
                "symbol": sym,
                "name": snap.get("name"),
                "research_date": day,
                "research_id": snap.get("research_id"),
                "leader_score": _signal_float(snap, "leader_score") or _signal_float(quant, "leader_score"),
                "candidate_score": _signal_float(snap, "candidate_score")
                or _signal_float(quant, "factor_score", "score"),
                "ml_prediction": _signal_float(snap, "ml_prediction", "ml_rank_score")
                or _signal_float(quant, "ml_prediction"),
                "profit_score": _signal_float(snap, "profit_score")
                or _signal_float(snap.get("profit_inflection") or {}, "score", "profit_score"),
                "event_score": _signal_float(snap, "event_score")
                or _signal_float(snap.get("event") or {}, "score", "event_score"),
                "news_score": _signal_float(snap, "news_score")
                or _signal_float(snap.get("news_package") or {}, "net_event_score", "news_intelligence_score"),
                "research_rating": rating,
                "rating_confidence": chair.get("confidence"),
                "trading_action": action,
                "role_scores": {
                    rid: {"score": op.get("score"), "stance": op.get("stance"), "status": op.get("status")}
                    for rid, op in roles.items()
                },
                "valuation_unavailable": str((roles.get("valuation") or {}).get("status") or "").lower()
                in {"unavailable", "skipped"},
                "risk_status": risk_status,
                "risk_flags": risk_flags,
                "committee_approve": approve,
                "canonical_joined": bool(joined),
                "direct_reason": _direct_block_reason(synth),
            }
            buy_rated_cases.append(case)

    # Also analyze ALL canonical decisions that are BUY-rated (may not have snapshot join)
    for d in canonical_rows:
        if str(d.get("research_rating") or "").upper() not in {"BUY", "STRONG_BUY"}:
            continue
        sym = to_symbol(str(d.get("symbol") or ""))
        if any(c.get("symbol") == sym and c.get("research_date") == d.get("_as_of") for c in buy_rated_cases):
            continue
        buy_rated_cases.append(
            {
                "symbol": sym,
                "name": d.get("name"),
                "research_date": d.get("_as_of") or d.get("as_of"),
                "research_id": d.get("research_id"),
                "candidate_score": d.get("candidate_score"),
                "research_rating": d.get("research_rating"),
                "rating_confidence": d.get("confidence") or d.get("ai_confidence"),
                "trading_action": d.get("trading_action"),
                "risk_status": d.get("risk_status"),
                "risk_flags": d.get("risk_flags"),
                "committee_approve": d.get("committee_approve"),
                "direct_reason": _direct_block_reason(d),
                "source": "canonical_only",
            }
        )

    # Session index ratings (lightweight)
    session_rating_c = Counter(str(s.get("rating") or "EMPTY").upper() for s in sessions)

    # Live reconciliation queue / meta (if any)
    live_recon = {
        "note": "Live reconciliation is advisory; not a BUY gate.",
        "pending_reassessments": 0,
        "trigger_counts": {},
        "state_counts_from_snapshot_meta": {},
    }
    qpath = root / "data" / "cache" / "live_reassessment.json"
    q = _load_json(qpath)
    if isinstance(q, dict):
        items = list((q.get("items") or {}).values())
        live_recon["pending_reassessments"] = sum(1 for i in items if i.get("status") == "pending")
        tc = Counter()
        for i in items:
            for t in i.get("trigger_codes") or []:
                tc[str(t)] += 1
            if i.get("primary_trigger"):
                tc[f"primary:{i.get('primary_trigger')}"] += 1
        live_recon["trigger_counts"] = dict(tc)
    # snapshot meta if present
    meta_states = Counter()
    for snap in snapshots:
        meta = snap.get("market_state_context_meta") if isinstance(snap.get("market_state_context_meta"), dict) else {}
        if meta.get("reconciliation_state"):
            meta_states[str(meta.get("reconciliation_state"))] += 1
        for t in meta.get("trigger_codes") or []:
            live_recon.setdefault("snapshot_trigger_counts", Counter())
            if isinstance(live_recon["snapshot_trigger_counts"], Counter):
                live_recon["snapshot_trigger_counts"][str(t)] += 1
    live_recon["state_counts_from_snapshot_meta"] = dict(meta_states)
    if isinstance(live_recon.get("snapshot_trigger_counts"), Counter):
        live_recon["snapshot_trigger_counts"] = dict(live_recon["snapshot_trigger_counts"])

    # Paper account
    paper = _load_json(root / "data" / "paper_state.json")
    paper_view = {}
    if isinstance(paper, dict):
        paper_view = {
            "cash": paper.get("cash") or paper.get("balance"),
            "equity": paper.get("equity"),
            "positions": len(paper.get("positions") or {}),
            "keys": sorted(list(paper.keys()))[:20],
        }

    # Aggregate threshold fails across reports (mean fail rate)
    threshold_summary = {}
    for k, rows in threshold_agg.items():
        fails = sum(int(r.get("fail") or 0) for r in rows)
        missing = sum(int(r.get("missing_or_unavailable") or r.get("missing_counted_as_fail") or 0) for r in rows)
        total = sum(int(r.get("fail") or 0) + int(r.get("pass") or 0) for r in rows)
        threshold_summary[k] = {
            "threshold": rows[0].get("threshold") if rows else None,
            "fail_sum": fails,
            "obs_sum": total,
            "fail_rate_pct": _pct(fails, total),
            "missing_sum": missing,
            "missing_rate_pct": _pct(missing, total + missing),
        }

    # Funnel table (report-based)
    # Use averages / totals carefully — for multi-day, show totals and per-day mean.
    n_reports = max(1, len(reports))
    buy_rating_n = rating_c.get("BUY", 0) + rating_c.get("STRONG_BUY", 0)
    small_pos_n = action_c.get("SMALL_POSITION", 0)
    risk_pass_n = (
        risk_status_c.get("pass", 0)
        + risk_status_c.get("ok", 0)
        + risk_status_c.get("PASS", 0)
        + risk_status_c.get("OK", 0)
    )
    approve_true = approve_c.get(True, 0)
    approve_false = approve_c.get(False, 0)
    final_buy = approve_true

    # First emptying gate
    stages = [
        ("Universe/Screen raw", funnel_sum["universe_raw"], funnel_sum["screen_filtered"]),
        ("Pool", funnel_sum["screen_filtered"] or funnel_sum["pool"], funnel_sum["pool"]),
        ("Candidate union", funnel_sum["pool"], funnel_sum["candidate_union"]),
        ("Council / platform reports", funnel_sum["candidate_union"], council_entered),
        ("BUY/STRONG_BUY rating", council_completed or council_entered, buy_rating_n),
        ("SMALL_POSITION action", buy_rating_n, small_pos_n),
        ("RiskFilter PASS", small_pos_n or buy_rating_n, risk_pass_n),
        ("committee_approve", small_pos_n, final_buy),
    ]

    bottleneck = _infer_bottlenecks(
        rating_c=rating_c,
        action_c=action_c,
        risk_status_c=risk_status_c,
        risk_flag_c=risk_flag_c,
        approve_c=approve_c,
        buy_rating_n=buy_rating_n,
        small_pos_n=small_pos_n,
        risk_pass_n=risk_pass_n,
        council_entered=council_entered,
        funnel_sum=funnel_sum,
        gate_reason_c=gate_reason_c,
        threshold_summary=threshold_summary,
        ml_dist=_score_dist(ml_scores),
        cand_dist=_score_dist(candidate_scores),
        buy_ready_c=buy_ready_c,
        snap_rating_c=snap_rating_c,
        snap_action_c=snap_action_c,
        config_view=config_view,
        buy_rated_cases=buy_rated_cases,
    )

    funnel_table = _build_funnel_table(
        reports=reports,
        funnel_sum=funnel_sum,
        council_entered=council_entered,
        council_completed=council_completed,
        rating_c=rating_c,
        action_c=action_c,
        risk_status_c=risk_status_c,
        approve_c=approve_c,
    )

    result = {
        "audit_version": "buy_pipeline_audit_v7d",
        "window": {"start": start.isoformat(), "end": end.isoformat(), "days": days},
        "data_coverage": {
            "dated_reports": [r.get("_as_of_date") for r in reports],
            "n_reports": len(reports),
            "n_snapshots": len(snapshots),
            "n_sessions": len(sessions),
            "n_production_cycles_deduped": len(cycles),
            "note": "Audit uses persisted reports/snapshots only; does not re-run research.",
        },
        "config": config_view,
        "layer_counts": {
            "Universe_raw_sum": funnel_sum["universe_raw"],
            "Screen_filtered_sum": funnel_sum["screen_filtered"],
            "Pool_sum": funnel_sum["pool"],
            "Candidate_union_sum": funnel_sum["candidate_union"],
            "Research_universe_sum": funnel_sum["research_universe"],
            "Gate_rejected_sum": funnel_sum["gate_rejected"],
            "Council_entered": council_entered,
            "Council_completed": council_completed,
            "Canonical_decisions": len(canonical_rows),
            "research_rating": dict(rating_c),
            "trading_action": dict(action_c),
            "RiskFilter_status": dict(risk_status_c),
            "RiskFilter_flags": dict(risk_flag_c),
            "committee_approve": {"true": approve_true, "false": approve_false},
            "Final_BUY": final_buy,
            "BUY_READY_signals": dict(buy_ready_c),
            "trade_timing_action": dict(timing_c),
        },
        "funnel_table": funnel_table,
        "research_gate": {
            "config": gate_cfg,
            "reject_reasons": dict(gate_reason_c),
            "threshold_independent_fail_rates": threshold_summary,
        },
        "candidate_score_distributions": {
            "candidate_score": _score_dist(candidate_scores),
            "leader_score": _score_dist(leader_scores),
            "ml_prediction": _score_dist(ml_scores),
            "profit_score": _score_dist(profit_scores),
            "event_score": _score_dist(event_scores),
            "news_score": _score_dist(news_scores),
        },
        "council_role_stats": {
            "snapshots_with_council": snap_n_with_council,
            "stance_counts": dict(role_stance_c),
            "score_distributions": {k: _score_dist(v) for k, v in role_scores.items()},
            "bear_negative_count": bear_negative,
            "valuation_unavailable_count": valuation_unavailable,
            "snapshot_ratings": dict(snap_rating_c),
            "snapshot_actions": dict(snap_action_c),
            "session_index_ratings": dict(session_rating_c),
            "historical_BUY_STRONG_BUY_share_pct": _pct(
                snap_rating_c.get("BUY", 0) + snap_rating_c.get("STRONG_BUY", 0),
                sum(snap_rating_c.values()) or 0,
            ),
        },
        "buy_rated_but_not_bought": buy_rated_cases,
        "roundtable": {
            "runs_in_window_reports": roundtable_runs,
            "details": roundtable_details,
            "note": "Legacy roundtable is benchmark-only when controls_trading=false; canonical_source=platform_council.",
        },
        "production_cycles": [
            {
                "as_of": c.get("as_of"),
                "cycle_id": c.get("cycle_id"),
                "candidate_count": c.get("candidate_count"),
                "research_count": c.get("research_count"),
                "buy_count": c.get("buy_count") if c.get("buy_count") is not None else c.get("BUY_count"),
                "paper_fill_count": c.get("paper_fill_count"),
            }
            for c in cycles
        ],
        "live_reconciliation": live_recon,
        "paper_account": paper_view,
        "keyword_counts": {
            "BUY_READY": buy_ready_c.get("universe_BUY_READY", 0) + buy_ready_c.get("canonical_BUY_READY", 0),
            "BUY_rating_canonical": rating_c.get("BUY", 0),
            "STRONG_BUY_rating_canonical": rating_c.get("STRONG_BUY", 0),
            "BUY_rating_snapshots": snap_rating_c.get("BUY", 0),
            "STRONG_BUY_rating_snapshots": snap_rating_c.get("STRONG_BUY", 0),
            "SMALL_POSITION_canonical": action_c.get("SMALL_POSITION", 0),
            "SMALL_POSITION_snapshots": snap_action_c.get("SMALL_POSITION", 0),
            "committee_approve_true": approve_true,
        },
        "bottlenecks": bottleneck,
        "answers": _answer_sheet(
            bottleneck,
            rating_c,
            action_c,
            risk_status_c,
            approve_c,
            buy_ready_c,
            funnel_sum,
            council_entered,
            config_view,
            live_recon,
            paper_view,
            buy_rated_cases,
            threshold_summary,
            _score_dist(ml_scores),
            _score_dist(candidate_scores),
        ),
    }
    # TODAY / window summary: why no BUY
    no_buy_c = Counter()
    for d in canonical_rows:
        if d.get("committee_approve"):
            continue
        no_buy_c[_direct_block_reason(d)] += 1
    latest_day = end.isoformat()
    day_reports = [r for r in reports if str(r.get("_as_of_date") or r.get("as_of") or "")[:10] == latest_day]
    day_canon = [d for d in canonical_rows if str(d.get("_as_of") or d.get("as_of") or "")[:10] == latest_day]
    result["today_buy_pipeline"] = {
        "as_of": latest_day,
        "n_reports": len(day_reports),
        "Candidates": sum(int(((r.get("candidate_union") or {}).get("n_union") or 0)) for r in day_reports),
        "Research": sum(int(((r.get("candidate_union") or {}).get("n_research") or 0)) for r in day_reports),
        "Council": sum(len(r.get("platform_reports") or []) for r in day_reports),
        "BUY_rating": sum(1 for d in day_canon if str(d.get("research_rating") or "").upper() == "BUY"),
        "STRONG_BUY": sum(1 for d in day_canon if str(d.get("research_rating") or "").upper() == "STRONG_BUY"),
        "READY_entry_setup": sum(
            1 for d in day_canon if str(d.get("entry_setup") or "").upper() == "READY" or str(d.get("trading_action") or "").upper() == "SMALL_POSITION"
        ),
        "Risk_PASS": sum(1 for d in day_canon if str(d.get("risk_status") or "").upper() in {"PASS", "OK"}),
        "Committee_approve": sum(1 for d in day_canon if d.get("committee_approve")),
        "Final_BUY": sum(1 for d in day_canon if d.get("committee_approve")),
        "top_rejection_reasons": dict(Counter(_direct_block_reason(d) for d in day_canon if not d.get("committee_approve")).most_common(8)),
        "NO_BUY_REASON": (
            Counter(_direct_block_reason(d) for d in day_canon if not d.get("committee_approve")).most_common(1)[0][0]
            if day_canon and not any(d.get("committee_approve") for d in day_canon)
            else ("HAS_BUY" if any(d.get("committee_approve") for d in day_canon) else "NO_CANONICAL_DECISIONS")
        ),
    }
    result["no_buy_reason_distribution"] = dict(no_buy_c)
    result["audit_version"] = f"buy_pipeline_audit_v{days}d"
    # Signal availability (missing vs zero) from universe rows when statuses present
    avail_stats: dict[str, Counter] = {
        k: Counter() for k in ("ml_prediction", "profit_score", "event_score", "news_score")
    }
    for r in reports:
        for row in ((r.get("candidate_union") or {}).get("universe") or []):
            if not isinstance(row, dict):
                continue
            for k in avail_stats:
                st = str(row.get(f"{k}_status") or "").upper()
                if st:
                    avail_stats[k][st] += 1
                elif row.get(f"{k}_available") is False:
                    avail_stats[k]["UNAVAILABLE"] += 1
                elif row.get(k) is None:
                    avail_stats[k]["MISSING"] += 1
                elif abs(float(row.get(k) or 0)) < 1e-15:
                    avail_stats[k]["ZERO"] += 1
                else:
                    avail_stats[k]["VALID"] += 1
    result["signal_availability"] = {k: dict(v) for k, v in avail_stats.items()}
    return result


def _build_funnel_table(
    *,
    reports: list[dict[str, Any]],
    funnel_sum: Counter,
    council_entered: int,
    council_completed: int,
    rating_c: Counter,
    action_c: Counter,
    risk_status_c: Counter,
    approve_c: Counter,
) -> list[dict[str, Any]]:
    buy_n = rating_c.get("BUY", 0) + rating_c.get("STRONG_BUY", 0)
    small = action_c.get("SMALL_POSITION", 0)
    risk_pass = (
        risk_status_c.get("pass", 0)
        + risk_status_c.get("ok", 0)
        + risk_status_c.get("PASS", 0)
        + risk_status_c.get("OK", 0)
    )
    approve_true = approve_c.get(True, 0)
    # Approximate sequential funnel using totals (multi-day summed).
    rows = [
        ("Universe raw (screen input)", funnel_sum["universe_raw"], funnel_sum["screen_filtered"]),
        ("Screen → Pool", funnel_sum["screen_filtered"] or funnel_sum["pool"], funnel_sum["pool"]),
        ("Pool → Candidate union", funnel_sum["pool"], funnel_sum["candidate_union"]),
        ("Candidate → Council entered", funnel_sum["candidate_union"], council_entered),
        ("Council completed", council_entered, council_completed),
        ("Council → BUY/STRONG_BUY", council_completed or council_entered, buy_n),
        ("BUY rating → SMALL_POSITION", buy_n, small),
        ("RiskFilter PASS (all canonical)", council_entered, risk_pass),
        ("committee_approve true", max(small, buy_n, 1) if (small or buy_n) else 0, approve_true),
    ]
    table = []
    for name, inp, passed in rows:
        inp_i = int(inp or 0)
        passed_i = int(passed or 0)
        # passed cannot exceed input for display sanity on sequential gates
        if name.startswith("BUY rating") or name.startswith("Council →"):
            rej = max(0, inp_i - passed_i)
        elif name.startswith("RiskFilter"):
            rej = max(0, inp_i - passed_i)
            # Risk pass is not strictly sequential from BUY; keep raw
        else:
            rej = max(0, inp_i - min(passed_i, inp_i))
            passed_i = min(passed_i, inp_i) if inp_i else passed_i
        table.append(
            {
                "stage": name,
                "input": inp_i,
                "passed": passed_i,
                "rejected": rej,
                "reject_rate_pct": _pct(rej, inp_i),
            }
        )
    return table


def _infer_bottlenecks(**kw: Any) -> list[dict[str, Any]]:
    rating_c: Counter = kw["rating_c"]
    action_c: Counter = kw["action_c"]
    risk_flag_c: Counter = kw["risk_flag_c"]
    buy_rating_n = kw["buy_rating_n"]
    small_pos_n = kw["small_pos_n"]
    council_entered = kw["council_entered"]
    gate_reason_c: Counter = kw["gate_reason_c"]
    snap_rating_c: Counter = kw["snap_rating_c"]
    snap_action_c: Counter = kw["snap_action_c"]
    buy_rated_cases = kw["buy_rated_cases"]
    cand_dist = kw["cand_dist"]
    ml_dist = kw["ml_dist"]
    threshold_summary = kw["threshold_summary"]
    config_view = kw["config_view"]

    findings: list[dict[str, Any]] = []

    # P-candidates based on evidence
    if council_entered > 0 and buy_rating_n == 0:
        findings.append(
            {
                "id": "COUNCIL_NO_BUY_RATING",
                "severity": "P0",
                "title": "Canonical path: Council/Chairman produced 0 BUY/STRONG_BUY",
                "evidence": f"Council entered={council_entered}, BUY+STRONG_BUY={buy_rating_n}, ratings={dict(rating_c)}",
            }
        )
    if buy_rating_n > 0 and small_pos_n == 0:
        findings.append(
            {
                "id": "NO_SMALL_POSITION",
                "severity": "P0",
                "title": "BUY ratings exist but trading_action never SMALL_POSITION",
                "evidence": f"BUY ratings={buy_rating_n}, SMALL_POSITION={small_pos_n}, actions={dict(action_c)}",
            }
        )
    if small_pos_n > 0 and kw["approve_c"].get(True, 0) == 0:
        findings.append(
            {
                "id": "APPROVE_COMPOUND_FAIL",
                "severity": "P0",
                "title": "SMALL_POSITION present but committee_approve never true",
                "evidence": f"SMALL_POSITION={small_pos_n}, approve_true=0, risk_flags={dict(risk_flag_c)}",
            }
        )
    if risk_flag_c.get("limit_up", 0) > 0:
        findings.append(
            {
                "id": "RISK_LIMIT_UP",
                "severity": "P1",
                "title": "RiskFilter systematically blocks limit-up opens",
                "evidence": f"limit_up flags={risk_flag_c.get('limit_up', 0)}, risk_status={dict(kw['risk_status_c'])}",
            }
        )
    deep = gate_reason_c.get("DEEP_BUDGET", 0) + gate_reason_c.get("LLM_BUDGET", 0)
    if deep > 0:
        findings.append(
            {
                "id": "RESEARCH_GATE_BUDGET",
                "severity": "P1",
                "title": "Research gate budget skips many names before full council",
                "evidence": f"gate reasons={dict(gate_reason_c)}",
            }
        )
    # Snapshot says historical BUY existed
    snap_buy = snap_rating_c.get("BUY", 0) + snap_rating_c.get("STRONG_BUY", 0)
    if snap_buy > 0 and buy_rating_n == 0:
        findings.append(
            {
                "id": "SNAPSHOT_BUY_NOT_IN_CANONICAL",
                "severity": "P1",
                "title": "Snapshots contain BUY ratings but dated report canonical_decisions do not",
                "evidence": (
                    f"snapshot BUY/STRONG_BUY={snap_buy}, snapshot SMALL_POSITION="
                    f"{snap_action_c.get('SMALL_POSITION', 0)}, canonical BUY={buy_rating_n}"
                ),
            }
        )
    if buy_rated_cases:
        reasons = Counter(str(c.get("direct_reason") or "") for c in buy_rated_cases)
        findings.append(
            {
                "id": "BUY_RATED_CASE_REASONS",
                "severity": "P1",
                "title": "Per-name reasons BUY-rated names did not become Final BUY",
                "evidence": dict(reasons),
            }
        )
    ml_fail = (threshold_summary.get("min_ml_prediction") or {}).get("fail_rate_pct")
    if ml_fail is not None and ml_fail >= 50:
        findings.append(
            {
                "id": "ML_HARD_THRESHOLD",
                "severity": "P2",
                "title": "ML prediction fails research_gate threshold on majority of candidates",
                "evidence": f"min_ml_prediction fail_rate={ml_fail}%, ml_dist={ml_dist}",
            }
        )
    if cand_dist.get("n", 0) and (cand_dist.get("p95") or 0) < float(
        (config_view.get("research_gate") or {}).get("min_candidate_score") or 0
    ):
        findings.append(
            {
                "id": "CANDIDATE_SCORE_TOO_LOW",
                "severity": "P2",
                "title": "Candidate scores mostly below min_candidate_score",
                "evidence": f"cand_dist={cand_dist}, min_candidate_score={(config_view.get('research_gate') or {}).get('min_candidate_score')}",
            }
        )

    # Ensure at least ordered P0/P1/P2
    sev_rank = {"P0": 0, "P1": 1, "P2": 2}
    findings.sort(key=lambda x: sev_rank.get(str(x.get("severity")), 9))
    # Label first three uniquely as P0/P1/P2 for report
    labeled = []
    for i, f in enumerate(findings[:3]):
        labeled.append({**f, "rank": f"P{i}"})
    if not labeled:
        labeled = [
            {
                "rank": "P0",
                "id": "NO_DATA",
                "title": "Insufficient dated reports in window",
                "evidence": "No clear bottleneck computed",
            }
        ]
    return labeled + findings[3:]


def _answer_sheet(
    bottlenecks,
    rating_c,
    action_c,
    risk_status_c,
    approve_c,
    buy_ready_c,
    funnel_sum,
    council_entered,
    config_view,
    live_recon,
    paper_view,
    buy_rated_cases,
    threshold_summary,
    ml_dist,
    cand_dist,
) -> dict[str, Any]:
    buy_n = rating_c.get("BUY", 0) + rating_c.get("STRONG_BUY", 0)
    return {
        "why_no_buy": bottlenecks[0] if bottlenecks else None,
        "too_few_candidates": funnel_sum.get("candidate_union", 0) == 0,
        "research_gate_too_strict": any(
            (threshold_summary.get(k) or {}).get("fail_rate_pct", 0) >= 70
            for k in ("min_candidate_score", "min_ml_prediction", "min_news_score")
        ),
        "ml_too_strict": (threshold_summary.get("min_ml_prediction") or {}).get("fail_rate_pct", 0) >= 50,
        "council_too_conservative": council_entered > 0 and buy_n == 0,
        "chairman_too_conservative": buy_n == 0 and council_entered > 0,
        "no_small_position": action_c.get("SMALL_POSITION", 0) == 0,
        "riskfilter_all_reject": (risk_status_c.get("pass", 0) + risk_status_c.get("ok", 0)) == 0
        and sum(risk_status_c.values()) > 0,
        "committee_approve_issue": approve_c.get(True, 0) == 0 and buy_n > 0,
        "paper_cash_lot_issue": bool(paper_view) and approve_c.get(True, 0) == 0,
        "live_recon_mis_kill": False,  # advisory only; not wired into approve
        "buy_ready_without_approve": (buy_ready_c.get("universe_BUY_READY", 0) > 0)
        and approve_c.get(True, 0) == 0,
        "roundtable_vs_council": {
            "canonical_source": config_view.get("decision.canonical_source"),
            "roundtable_controls_trading": config_view.get("decision.roundtable_controls_trading"),
        },
        "ml_dist": ml_dist,
        "candidate_dist": cand_dist,
        "n_buy_rated_cases_explained": len(buy_rated_cases),
        "live_recon_summary": {
            "pending": live_recon.get("pending_reassessments"),
            "states": live_recon.get("state_counts_from_snapshot_meta"),
        },
    }


def render_markdown(result: dict[str, Any]) -> str:
    w = result.get("window") or {}
    lines: list[str] = []
    lines.append("# LongTanRadar 7-Day BUY Pipeline Audit")
    lines.append("")
    lines.append(f"**Window:** {w.get('start')} → {w.get('end')} ({w.get('days')} days)")
    cov = result.get("data_coverage") or {}
    lines.append(
        f"**Data:** reports={cov.get('n_reports')} {cov.get('dated_reports')}; "
        f"snapshots={cov.get('n_snapshots')}; sessions={cov.get('n_sessions')}; "
        f"cycles={cov.get('n_production_cycles_deduped')}"
    )
    lines.append("")
    lines.append("> Read-only audit. No BUY gates / RiskFilter / prompts / thresholds were modified.")
    lines.append("")

    lines.append("## Config snapshot (execution path)")
    lines.append("")
    cfg = result.get("config") or {}
    for k in [
        "trading.mode",
        "broker.mode",
        "agent.autostart",
        "research.enabled",
        "ai.enabled",
        "ai.roundtable",
        "ai.roundtable_mode",
        "decision.canonical_source",
        "decision.roundtable_controls_trading",
        "paper.initial_balance",
        "trading.lot_size",
        "universe.screen.max_price",
    ]:
        lines.append(f"- `{k}` = `{cfg.get(k)}`")
    lines.append("")
    lines.append(
        "**Important:** `roundtable_controls_trading=false` and "
        "`canonical_source=platform_council` — legacy Roundtable is **not** the trade decision path."
    )
    lines.append("")

    lc = result.get("layer_counts") or {}
    lines.append("## Layer counts (summed over dated reports in window)")
    lines.append("")
    lines.append(f"- Universe raw: **{lc.get('Universe_raw_sum')}**")
    lines.append(f"- Screen filtered: **{lc.get('Screen_filtered_sum')}**")
    lines.append(f"- Pool: **{lc.get('Pool_sum')}**")
    lines.append(f"- Candidate union: **{lc.get('Candidate_union_sum')}**")
    lines.append(f"- Research universe field: **{lc.get('Research_universe_sum')}**")
    lines.append(f"- Council entered (platform_reports): **{lc.get('Council_entered')}**")
    lines.append(f"- Council completed: **{lc.get('Council_completed')}**")
    lines.append(f"- research_rating: `{lc.get('research_rating')}`")
    lines.append(f"- trading_action: `{lc.get('trading_action')}`")
    lines.append(f"- RiskFilter status: `{lc.get('RiskFilter_status')}`")
    lines.append(f"- RiskFilter flags: `{lc.get('RiskFilter_flags')}`")
    lines.append(f"- committee_approve: `{lc.get('committee_approve')}`")
    lines.append(f"- Final BUY: **{lc.get('Final_BUY')}**")
    lines.append(f"- BUY_READY signals: `{lc.get('BUY_READY_signals')}`")
    lines.append("")

    today = result.get("today_buy_pipeline") or {}
    lines.append("## TODAY BUY PIPELINE")
    lines.append("")
    lines.append(f"- as_of: **{today.get('as_of')}**")
    lines.append(f"- Candidates: **{today.get('Candidates')}**")
    lines.append(f"- Research: **{today.get('Research')}**")
    lines.append(f"- Council: **{today.get('Council')}**")
    lines.append(f"- BUY rating: **{today.get('BUY_rating')}**")
    lines.append(f"- STRONG_BUY: **{today.get('STRONG_BUY')}**")
    lines.append(f"- READY entry setup: **{today.get('READY_entry_setup')}**")
    lines.append(f"- Risk PASS: **{today.get('Risk_PASS')}**")
    lines.append(f"- Committee approve: **{today.get('Committee_approve')}**")
    lines.append(f"- Final BUY: **{today.get('Final_BUY')}**")
    lines.append(f"- NO_BUY_REASON: **{today.get('NO_BUY_REASON')}**")
    lines.append(f"- Top rejection reasons: `{today.get('top_rejection_reasons')}`")
    lines.append("")
    lines.append(f"- Window no_buy_reason_distribution: `{result.get('no_buy_reason_distribution')}`")
    lines.append(f"- Signal availability (missing≠zero): `{result.get('signal_availability')}`")
    lines.append("")

    lines.append("## Funnel table")
    lines.append("")
    lines.append("| Stage | Input | Passed | Rejected | Reject Rate |")
    lines.append("|---|---:|---:|---:|---:|")
    for row in result.get("funnel_table") or []:
        lines.append(
            f"| {row.get('stage')} | {row.get('input')} | {row.get('passed')} | "
            f"{row.get('rejected')} | {row.get('reject_rate_pct')}% |"
        )
    lines.append("")

    lines.append("## Research gate")
    lines.append("")
    rg = result.get("research_gate") or {}
    lines.append(f"- config: `{rg.get('config')}`")
    lines.append(f"- reject reasons: `{rg.get('reject_reasons')}`")
    lines.append("")
    lines.append("| Threshold | Value | Fail rate | Fail sum | Obs |")
    lines.append("|---|---:|---:|---:|---:|")
    for k, v in (rg.get("threshold_independent_fail_rates") or {}).items():
        lines.append(
            f"| {k} | {v.get('threshold')} | {v.get('fail_rate_pct')}% | {v.get('fail_sum')} | {v.get('obs_sum')} |"
        )
    lines.append("")
    lines.append(
        "Note: independent fail rates treat missing values as fail — useful to spot hard fields "
        "(e.g. ML often missing on rows)."
    )
    lines.append("")

    lines.append("## Score distributions (candidate universe rows)")
    lines.append("")
    for name, dist in (result.get("candidate_score_distributions") or {}).items():
        lines.append(f"- **{name}**: `{dist}`")
    lines.append("")

    crs = result.get("council_role_stats") or {}
    lines.append("## Council / Chairman (snapshots in window)")
    lines.append("")
    lines.append(f"- snapshots_with_council: **{crs.get('snapshots_with_council')}**")
    lines.append(f"- snapshot ratings: `{crs.get('snapshot_ratings')}`")
    lines.append(f"- snapshot actions: `{crs.get('snapshot_actions')}`")
    lines.append(f"- session index ratings: `{crs.get('session_index_ratings')}`")
    lines.append(f"- BUY/STRONG_BUY share: **{crs.get('historical_BUY_STRONG_BUY_share_pct')}%**")
    lines.append(f"- bear_negative_count: **{crs.get('bear_negative_count')}**")
    lines.append(f"- valuation_unavailable_count: **{crs.get('valuation_unavailable_count')}**")
    lines.append(f"- stance_counts: `{crs.get('stance_counts')}`")
    for rid, dist in (crs.get("score_distributions") or {}).items():
        lines.append(f"- role `{rid}` scores: `{dist}`")
    lines.append("")

    lines.append("## BUY-rated but not Final BUY (case-by-case)")
    lines.append("")
    cases = result.get("buy_rated_but_not_bought") or []
    if not cases:
        lines.append("_No BUY/STRONG_BUY cases found in window snapshots/canonical join._")
    for c in cases:
        lines.append(f"### {c.get('symbol')} ({c.get('research_date')})")
        lines.append(
            f"- rating={c.get('research_rating')} conf={c.get('rating_confidence')} "
            f"action={c.get('trading_action')}"
        )
        lines.append(
            f"- scores: candidate={c.get('candidate_score')} leader={c.get('leader_score')} "
            f"ml={c.get('ml_prediction')} profit={c.get('profit_score')} "
            f"event={c.get('event_score')} news={c.get('news_score')}"
        )
        lines.append(
            f"- risk={c.get('risk_status')} flags={c.get('risk_flags')} "
            f"approve={c.get('committee_approve')}"
        )
        lines.append(f"- **direct_reason:** `{c.get('direct_reason')}`")
        if c.get("role_scores"):
            lines.append(f"- role_scores: `{c.get('role_scores')}`")
        lines.append("")

    lines.append("## Roundtable vs Platform Council")
    lines.append("")
    rt = result.get("roundtable") or {}
    lines.append(f"- report roundtable entries: `{rt.get('details')}`")
    lines.append(f"- note: {rt.get('note')}")
    lines.append("")

    lines.append("## Production cycles")
    lines.append("")
    for c in result.get("production_cycles") or []:
        lines.append(
            f"- {c.get('as_of')} `{c.get('cycle_id')}` candidates={c.get('candidate_count')} "
            f"research={c.get('research_count')} buy={c.get('buy_count')} fills={c.get('paper_fill_count')}"
        )
    lines.append("")

    lines.append("## Live reconciliation (advisory only)")
    lines.append("")
    lines.append(f"`{result.get('live_reconciliation')}`")
    lines.append("")

    lines.append("## Paper account")
    lines.append("")
    lines.append(f"`{result.get('paper_account')}`")
    lines.append("")

    lines.append("## Keyword counts")
    lines.append("")
    lines.append(f"`{result.get('keyword_counts')}`")
    lines.append("")

    lines.append("## Bottlenecks (ranked)")
    lines.append("")
    for b in result.get("bottlenecks") or []:
        lines.append(f"### {b.get('rank')}: {b.get('title')}")
        lines.append(f"- id: `{b.get('id')}`")
        lines.append(f"- evidence: `{b.get('evidence')}`")
        lines.append("")

    lines.append("## Final answers")
    lines.append("")
    ans = result.get("answers") or {}
    for k, v in ans.items():
        lines.append(f"- **{k}:** `{v}`")
    lines.append("")
    lines.append("---")
    lines.append("Audit complete. No strategy parameters were changed.")
    return "\n".join(lines)


def write_audit_outputs(cfg: dict[str, Any], result: dict[str, Any]) -> dict[str, str]:
    root = _root(cfg)
    out_dir = root / "docs" / "research"
    out_dir.mkdir(parents=True, exist_ok=True)
    days = int(((result.get("window") or {}).get("days")) or 7)
    stem = f"BUY_PIPELINE_AUDIT_{days}D"
    md_path = out_dir / f"{stem}.md"
    json_path = out_dir / f"{stem}.json"
    md_path.write_text(render_markdown(result), encoding="utf-8")
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return {"markdown": str(md_path), "json": str(json_path)}
