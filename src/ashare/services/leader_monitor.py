from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ashare.config_loaders import load_yaml_config
from ashare.symbols import to_symbol


def _load_latest_report(cfg: dict[str, Any]) -> dict[str, Any]:
    root = Path(cfg.get("_root") or ".")
    p = root / "data" / "reports" / "latest.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _normalize_watch(raw: Any) -> dict[str, dict[str, Any]]:
    """Accept dict, {items: [...]}, or list of row dicts."""
    if not raw:
        return {}
    if isinstance(raw, list):
        return {to_symbol(x["symbol"]): x for x in raw if isinstance(x, dict) and x.get("symbol")}
    if isinstance(raw, dict):
        if "items" in raw and isinstance(raw.get("items"), list):
            return {
                to_symbol(i["symbol"]): i
                for i in (raw.get("items") or [])
                if isinstance(i, dict) and i.get("symbol")
            }
        # already symbol -> row
        if all(isinstance(v, dict) for v in raw.values()):
            return {to_symbol(k): v for k, v in raw.items() if isinstance(v, dict)}
    return {}


def _load_disk_focus(cfg: dict[str, Any]) -> dict[str, dict[str, Any]]:
    try:
        from ashare.leader.focus_watchlist import FocusWatchlistStore

        return FocusWatchlistStore(cfg).load()
    except Exception:
        return {}


def build_leader_monitor(cfg: dict[str, Any], report: dict[str, Any] | None = None) -> dict[str, Any]:
    report = report or _load_latest_report(cfg)
    lc = load_yaml_config(cfg, "leader")
    focus = (report.get("candidate_union") or {}).get("leader_pipeline") or {}
    watch = _normalize_watch(focus.get("focus_watchlist"))
    if not watch:
        watch = _load_disk_focus(cfg)

    rows: list[dict[str, Any]] = []
    cu = report.get("candidate_union") or {}
    sources: list[Any] = [
        list(cu.get("universe") or []),
        list(cu.get("research_universe") or []),
        list(report.get("platform_reports") or []),
        list(watch.values()),
    ]
    # Prefer dry-run snapshot when latest research has empty leader pipeline
    dry_path = Path(cfg.get("_root") or ".") / "data" / "leader" / "dry_run_latest.json"
    if dry_path.exists() and not focus:
        try:
            dry = json.loads(dry_path.read_text(encoding="utf-8"))
            dm = dry.get("leader_monitor") or {}
            for bucket_rows in (dm.get("buckets") or {}).values():
                sources.append(list(bucket_rows or []))
            if not watch:
                watch = _normalize_watch(dm.get("focus_watchlist") or dry.get("focus_watchlist"))
            if not focus:
                focus = {
                    "dashboard": {
                        "stage_performance": dm.get("stage_performance") or {},
                        "board_performance": dm.get("board_performance") or {},
                    },
                    "focus_stats": dm.get("focus_stats") or dry.get("focus_stats") or {},
                }
        except Exception:
            pass

    for src in sources:
        for r in src:
            if not isinstance(r, dict):
                continue
            sym = to_symbol(r.get("symbol") or "")
            if not sym:
                continue
            if any(x.get("symbol") == sym for x in rows):
                continue
            pr = next((p for p in (report.get("platform_reports") or []) if p.get("symbol") == sym), {}) or {}
            cd = next((d for d in (report.get("canonical_decisions") or []) if d.get("symbol") == sym), {}) or {}
            w = watch.get(sym) or {}
            leader = pr.get("leader") if isinstance(pr.get("leader"), dict) else {}
            chairman = pr.get("chairman") if isinstance(pr.get("chairman"), dict) else {}
            rows.append(
                {
                    "symbol": sym,
                    "name": r.get("name") or pr.get("name") or w.get("name"),
                    "lifecycle": r.get("lifecycle") or leader.get("lifecycle") or w.get("lifecycle"),
                    "board_count": r.get("board_count") or w.get("board_count"),
                    "leader_score": r.get("leader_score") or w.get("leader_score"),
                    "stage": r.get("stage") or leader.get("stage") or w.get("stage"),
                    "chase_score": r.get("chase_score") or leader.get("chase_score") or w.get("chase_score"),
                    "chase_level": r.get("chase_level") or w.get("chase_level"),
                    "trade_timing_score": r.get("trade_timing_score")
                    or leader.get("trade_timing_score")
                    or w.get("trade_timing_score"),
                    "trade_timing_action": r.get("trade_timing_action")
                    or leader.get("trade_timing_action")
                    or w.get("trade_timing_action"),
                    "reentry_score": r.get("reentry_score") or w.get("reentry_score"),
                    "reentry_phase": r.get("reentry_phase") or w.get("reentry_phase"),
                    "focus_tier": r.get("focus_tier") or w.get("focus_tier"),
                    "entry_timeline": r.get("entry_timeline") or w.get("entry_timeline"),
                    "news_score": r.get("news_score") or w.get("news_score"),
                    "risk_status": cd.get("risk_status"),
                    "risk_flags": cd.get("risk_flags"),
                    "council_rating": chairman.get("rating") or cd.get("research_rating"),
                    "status_reason": r.get("status_reason") or w.get("status_reason"),
                    "in_focus_watchlist": bool(w) or bool(r.get("in_focus_watchlist")),
                    "merged_from_focus": bool(r.get("merged_from_focus")),
                }
            )

    buckets = {
        "FOCUS": [],
        "BUY_CANDIDATE": [],
        "BUY_READY": [],
        "WAIT": [],
        "DROPPED": [],
        "OTHER": [],
    }
    for row in rows:
        lc_state = str(row.get("lifecycle") or row.get("trade_timing_action") or "OTHER").upper()
        if lc_state in buckets:
            buckets[lc_state].append(row)
        elif str(row.get("trade_timing_action") or "").upper() == "WAIT":
            buckets["WAIT"].append(row)
        else:
            buckets["OTHER"].append(row)

    buy_ready = buckets["BUY_READY"]
    dashboard = focus.get("dashboard") or {}
    research_date = report.get("as_of")
    # Live Quote Overlay + State Reconciliation: attach live_*/reconciliation only.
    # Never rewrite research snapshot fields (board_count, leader_score, stage, …).
    try:
        from ashare.services.live_quote_overlay import attach_live_quote_overlay
        from ashare.services.state_reconciliation import attach_reconciliation_overlay

        for bucket_rows in buckets.values():
            for row in bucket_rows:
                if research_date and not row.get("research_date"):
                    row["research_date"] = research_date
            attach_live_quote_overlay(bucket_rows, cfg=cfg, research_date=research_date)
            attach_reconciliation_overlay(bucket_rows, cfg=cfg)
    except Exception:
        # Overlay failure must not break monitor / research payload.
        for bucket_rows in buckets.values():
            for row in bucket_rows:
                if research_date and not row.get("research_date"):
                    row["research_date"] = research_date
                row.setdefault("live_status", "UNKNOWN")
                row.setdefault("reconciliation_state", "UNKNOWN")

    return {
        "enabled": bool(lc.get("enabled", True)),
        "research_only": bool(lc.get("research_only", True)),
        "positioning": (lc.get("product") or {}).get("positioning"),
        "buy_ready_count": len(buy_ready),
        "focus_count": len(buckets["FOCUS"]) + len(buckets["BUY_CANDIDATE"]) + len(buy_ready),
        "has_buy_ready": len(buy_ready) > 0,
        "message": (
            "当前没有满足交易条件的龙头"
            if not buy_ready
            else f"有 {len(buy_ready)} 只龙头进入「可买入」"
        ),
        "buckets": buckets,
        "focus_watchlist": list(watch.values()),
        "stage_performance": dashboard.get("stage_performance") or {},
        "board_performance": dashboard.get("board_performance") or {},
        "focus_stats": focus.get("focus_stats") or {},
        "as_of": research_date,
        "research_date": research_date,
    }
