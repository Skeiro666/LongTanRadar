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


def build_leader_monitor(cfg: dict[str, Any], report: dict[str, Any] | None = None) -> dict[str, Any]:
    report = report or _load_latest_report(cfg)
    lc = load_yaml_config(cfg, "leader")
    focus = (report.get("candidate_union") or {}).get("leader_pipeline") or {}
    watch = focus.get("focus_watchlist") or {}
    if isinstance(watch, dict) and "items" in watch:
        watch = {to_symbol(i["symbol"]): i for i in watch.get("items") or [] if i.get("symbol")}

    rows: list[dict[str, Any]] = []
    cu = report.get("candidate_union") or {}
    for src in (
        list(cu.get("universe") or []),
        list(cu.get("research_universe") or []),
        list(report.get("platform_reports") or []),
        list((focus.get("focus_watchlist") or {}).values())
        if isinstance(focus.get("focus_watchlist"), dict)
        else list(focus.get("focus_watchlist") or []),
    ):
        for r in src:
            sym = to_symbol(r.get("symbol") or "")
            if not sym:
                continue
            if any(x.get("symbol") == sym for x in rows):
                continue
            pr = next((p for p in (report.get("platform_reports") or []) if p.get("symbol") == sym), {})
            cd = next((d for d in (report.get("canonical_decisions") or []) if d.get("symbol") == sym), {})
            w = watch.get(sym) or {}
            leader = pr.get("leader") or {}
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
                    "news_score": r.get("news_score") or w.get("news_score"),
                    "risk_status": cd.get("risk_status"),
                    "risk_flags": cd.get("risk_flags"),
                    "council_rating": (pr.get("chairman") or {}).get("rating") or cd.get("research_rating"),
                    "status_reason": r.get("status_reason") or w.get("status_reason"),
                    "in_focus_watchlist": bool(w) or bool(r.get("in_focus_watchlist")),
                    "merged_from_focus": bool(r.get("merged_from_focus")),
                }
            )

    for item in list(watch.values()) if isinstance(watch, dict) else []:
        sym = to_symbol(item.get("symbol") or "")
        if not sym or any(x.get("symbol") == sym for x in rows):
            continue
        rows.append(
            {
                "symbol": sym,
                "name": item.get("name"),
                "lifecycle": item.get("lifecycle"),
                "board_count": item.get("board_count"),
                "leader_score": item.get("leader_score"),
                "stage": item.get("stage"),
                "chase_score": item.get("chase_score"),
                "chase_level": item.get("chase_level"),
                "trade_timing_score": item.get("trade_timing_score"),
                "trade_timing_action": item.get("trade_timing_action"),
                "news_score": item.get("news_score"),
                "status_reason": item.get("status_reason"),
                "in_focus_watchlist": True,
                "merged_from_focus": True,
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
            else f"有 {len(buy_ready)} 只龙头进入 BUY_READY"
        ),
        "buckets": buckets,
        "focus_watchlist": list(watch.values()) if isinstance(watch, dict) else [],
        "stage_performance": dashboard.get("stage_performance") or {},
        "board_performance": dashboard.get("board_performance") or {},
        "focus_stats": focus.get("focus_stats") or {},
        "as_of": report.get("as_of"),
    }
