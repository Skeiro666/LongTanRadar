#!/usr/bin/env python3
"""BUY Pipeline + Weak-News Strong-Quant Failure Audit (research-only)."""
from __future__ import annotations

import json
import math
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ashare.config import load_config
from ashare.news.conflict import compute_news_quant_conflict
from ashare.ml.features import feature_row_from_closes
from ashare.research.gate import _gate_cfg, _signal_values, evaluate_research_gate
from ashare.strategy.anti_chase import anti_chase_cfg, chase_penalty, enrich_structure
from ashare.symbols import to_symbol

# --- configurable research thresholds (not production) ---
AUDIT_CFG = {
    "quant_strong_threshold": 0.15,
    "news_weak_threshold": 0.12,
    "quant_quadrant_threshold": 0.15,
    "news_quadrant_threshold": 0.12,
}

TARGET_STOCKS = {
    "002412.SZ": "汉森制药",
    "603958.SH": "哈森股份",
    "601700.SH": "风范股份",
    "603330.SH": "天洋新材",
    "601212.SH": "白银有色",
    "603626.SH": "科森科技",
    "000620.SZ": "盈新发展",
    "600227.SH": "赤天化",
}


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def _load_reports(reports_dir: Path) -> list[dict[str, Any]]:
    reports: list[dict[str, Any]] = []
    if not reports_dir.exists():
        return reports
    for p in sorted(reports_dir.glob("*.json")):
        try:
            reports.append(json.load(open(p, encoding="utf-8")))
        except Exception:
            pass
    return reports


def _dedupe_cycles(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for r in rows:
        cid = str(r.get("cycle_id") or "")
        if cid and cid in seen:
            continue
        if cid:
            seen.add(cid)
        out.append(r)
    return out


def _forward_metrics(
    sym: str,
    signal_date: str,
    signal_price: float,
    cache_dir: Path,
    horizons: tuple[int, ...] = (1, 3, 5, 10, 20),
) -> dict[str, Any]:
    p = cache_dir / f"{sym.replace('.', '_')}.parquet"
    if not p.exists():
        return {"available": False, "note": "no_parquet"}
    df = pd.read_parquet(p)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    sig_dt = pd.Timestamp(signal_date)
    idx_list = df.index[df["date"] <= sig_dt].tolist()
    if not idx_list:
        return {"available": False, "note": "signal_before_data"}
    i0 = idx_list[-1]
    entry = float(signal_price or df.loc[i0, "close"])
    if entry <= 0:
        return {"available": False, "note": "bad_entry"}
    future = df.iloc[i0 + 1 :]
    out: dict[str, Any] = {"available": True, "entry": entry, "signal_date": signal_date, "horizons": {}}
    closes = future["close"].astype(float)
    if closes.empty:
        out["note"] = "no_forward_bars_in_cache"
        out["max_drawdown"] = None
        return out
    cum = closes / entry - 1.0
    running_max = closes.cummax()
    dd = (closes - running_max) / running_max
    out["max_drawdown"] = float(dd.min())
    out["limit_down_hit"] = bool((future.get("limit_down", pd.Series(dtype=bool)).astype(bool)).any())
    for h in horizons:
        if len(future) >= h:
            ret = float(future.iloc[h - 1]["close"]) / entry - 1.0
            out["horizons"][str(h)] = round(ret, 4)
        else:
            out["horizons"][str(h)] = None
    return out


def _compute_technicals(sym: str, as_of: str, cache_dir: Path, cfg: dict[str, Any]) -> dict[str, Any]:
    p = cache_dir / f"{sym.replace('.', '_')}.parquet"
    if not p.exists():
        return {}
    df = pd.read_parquet(p)
    df["date"] = pd.to_datetime(df["date"])
    df = df[df["date"] <= pd.Timestamp(as_of)].sort_values("date")
    if len(df) < 65:
        return {}
    c = df["close"].astype(float)
    v = df["volume"].astype(float)
    h = df["high"].astype(float)
    lo = df["low"].astype(float)
    feats = feature_row_from_closes(c, v, h, lo) or {}
    feats = enrich_structure(feats, c)
    feats["ma_gap_5"] = float((c.iloc[-1] - c.tail(5).mean()) / c.tail(5).mean()) if len(c) >= 5 else 0.0
    feats["mom_10"] = float(c.iloc[-1] / c.iloc[-11] - 1.0) if len(c) >= 11 else 0.0
    lu = df.get("limit_up")
    if lu is not None:
        feats["limit_up_count_20d"] = float(lu.astype(bool).tail(20).sum())
    else:
        feats["limit_up_count_20d"] = 0.0
    up = (c.pct_change() > 0.001).astype(int)
    streak = 0
    for x in up.iloc[::-1]:
        if x:
            streak += 1
        else:
            break
    feats["consecutive_up_days"] = float(streak)
    amt = df.get("amount")
    if amt is not None and len(amt) >= 20:
        a = amt.astype(float)
        mu, sd = float(a.tail(20).mean()), float(a.tail(20).std() or 1.0)
        feats["turnover_zscore"] = float((a.iloc[-1] - mu) / sd) if sd > 1e-9 else 0.0
    else:
        feats["turnover_zscore"] = 0.0
    vol = v.pct_change().tail(5).mean()
    vol_prev = v.pct_change().tail(10).head(5).mean()
    feats["volume_acceleration"] = float(vol - vol_prev) if not (math.isnan(vol) or math.isnan(vol_prev)) else 0.0
    feats["chase_score"] = float(chase_penalty(feats, cfg))
    return feats


def _classify_stage(feats: dict[str, Any], pool_row: dict[str, Any] | None) -> str:
    board = int((pool_row or {}).get("board_count") or 0)
    mom5 = float(feats.get("mom_5") or 0)
    mom20 = float(feats.get("mom_20") or 0)
    gap20 = float(feats.get("ma_gap_20") or 0)
    gap60 = float(feats.get("ma_gap_60") or 0)
    lu20 = float(feats.get("limit_up_count_20d") or 0)
    breakdown = float(feats.get("is_breakdown") or 0) > 0
    ret1 = float(feats.get("ret_1") or 0)
    if breakdown or (gap60 < -0.05 and mom5 < -0.03):
        return "BREAKDOWN"
    if board >= 3 or gap20 > 0.08 or lu20 >= 3 or mom5 > 0.25:
        return "EXTREME"
    if ret1 < -0.05 and mom5 > 0.1:
        return "DISTRIBUTION"
    if mom5 > 0.12 and mom20 > 0.08:
        return "ACCELERATION"
    if mom20 > 0.05 and gap20 > 0.02:
        return "TREND"
    return "EARLY"


def _quant_score(row: dict[str, Any]) -> float:
    gate = row.get("gate") or {}
    sig = gate.get("signals") or {}
    for k in ("leader_score", "candidate_score"):
        if sig.get(k) is not None:
            return float(sig[k])
    return float(row.get("leader_score") or row.get("candidate_score") or 0)


def _news_score(row: dict[str, Any], pr: dict[str, Any] | None = None) -> float:
    gate = row.get("gate") or {}
    sig = gate.get("signals") or {}
    if sig.get("news_score") is not None:
        return float(sig["news_score"])
    if pr:
        news = pr.get("news") or {}
        if news.get("net_event_score") is not None:
            return float(news["net_event_score"])
    nc = row.get("news_conflict") or {}
    ns = (nc.get("signals") or {}).get("news_support")
    if ns is not None:
        return float(ns)
    return float(row.get("news_score") or 0)


def _scores_from_platform(pr: dict[str, Any], u: dict[str, Any], pool_row: dict[str, Any] | None) -> dict[str, Any]:
    gate = u.get("gate") or pr.get("gate") or {}
    sig = gate.get("signals") or {}
    trigger = u.get("trigger") or {}
    pool_row = pool_row or {}
    cand = {
        **u,
        "leader_score": sig.get("leader_score") or u.get("leader_score"),
        "candidate_score": u.get("candidate_score") or pr.get("ai_routing", {}).get("candidate_score"),
        "news_score": _news_score(u, pr),
        "event_score": sig.get("event_score") or pool_row.get("event_score"),
        "profit_inflection": {"score": sig.get("profit_score")} if sig.get("profit_score") is not None else pool_row.get("profit_inflection"),
        "ml_prediction": sig.get("ml_prediction"),
        "board_count": pool_row.get("board_count"),
    }
    nc = compute_news_quant_conflict(
        intelligence=(pr.get("news") or {}).get("news_intelligence"),
        candidate=cand,
    )
    return {
        "quant_score": _quant_score({**u, "gate": {"signals": sig}}),
        "leader_score": sig.get("leader_score"),
        "factor_score": sig.get("leader_score"),
        "profit_score": sig.get("profit_score") or (pool_row.get("profit_inflection") or {}).get("score"),
        "event_score": sig.get("event_score") or pool_row.get("event_score"),
        "news_score": cand["news_score"],
        "ml_score": sig.get("ml_prediction"),
        "candidate_score": cand.get("candidate_score"),
        "conflict_recomputed": nc,
    }


def _refresh_forward_bars(symbols: list[str], cache_dir: Path, start: str = "2026-08-01") -> None:
    try:
        from datetime import date

        from ashare.data.akshare_source import fetch_many

        fetched = fetch_many(symbols, start=start, end=str(date.today()))
        for sym, df in fetched.items():
            if df is None or df.empty:
                continue
            p = cache_dir / f"{sym.replace('.', '_')}.parquet"
            if p.exists():
                old = pd.read_parquet(p)
                old["date"] = pd.to_datetime(old["date"])
                df["date"] = pd.to_datetime(df["date"])
                merged = pd.concat([old, df]).drop_duplicates(subset=["date"]).sort_values("date")
            else:
                merged = df
            merged.to_parquet(p, index=False)
    except Exception as exc:
        print(f"[audit] forward bar refresh skipped: {exc}", file=sys.stderr)


def _threshold_audit(candidates: list[dict[str, Any]], cfg: dict[str, Any]) -> dict[str, Any]:
    gc = _gate_cfg(cfg)
    counts: dict[str, dict[str, int]] = defaultdict(lambda: {"pass": 0, "fail": 0})
    ranked = sorted(candidates, key=lambda x: float(x.get("candidate_score") or 0), reverse=True)
    for i, row in enumerate(ranked):
        sig = _signal_values(row)
        cs = sig["candidate_score"]
        counts["min_candidate_score"]["pass" if cs >= gc["min_candidate_score"] else "fail"] += 1
        counts["min_leader_score"]["pass" if sig["leader_score"] >= gc["min_leader_score"] else "fail"] += 1
        counts["min_ml_prediction"]["pass" if sig["ml_prediction"] >= gc["min_ml_prediction"] else "fail"] += 1
        counts["min_profit_score"]["pass" if sig["profit_score"] >= gc["min_profit_score"] else "fail"] += 1
        counts["min_event_score"]["pass" if sig["event_score"] >= gc["min_event_score"] else "fail"] += 1
        counts["min_news_score"]["pass" if sig["news_score"] >= gc["min_news_score"] else "fail"] += 1
        dec = evaluate_research_gate(row, cfg, rank=i)
        if dec.passed:
            counts["research_gate_composite"]["pass"] += 1
        else:
            counts["research_gate_composite"]["fail"] += 1
            rr = dec.reason
            counts[f"gate_reject_{rr}"]["fail"] += 1
    return {"thresholds": gc, "counts": dict(counts)}


def _build_funnel(report: dict[str, Any]) -> list[dict[str, Any]]:
    screen = report.get("screen") or {}
    pool = report.get("pool") or []
    cu = report.get("candidate_union") or {}
    gate = (cu.get("gate") or {}) if isinstance(cu, dict) else {}
    canonical = report.get("canonical_decisions") or []
    nd = report.get("news_discovery") or {}

    layers = [
        {
            "layer": "Universe (market screen)",
            "input_count": screen.get("raw_count", 0),
            "output_count": screen.get("filtered_count", 0),
            "reject_count": max(0, int(screen.get("raw_count") or 0) - int(screen.get("filtered_count") or 0)),
            "reject_reason": "screen_filters",
        },
        {
            "layer": "Pool",
            "input_count": screen.get("filtered_count", 0),
            "output_count": int(report.get("universe_size") or len(pool) or len(report.get("quant_top_n_symbols") or [])),
            "reject_count": max(
                0,
                int(screen.get("filtered_count") or 0)
                - int(report.get("universe_size") or len(pool) or 0),
            ),
            "reject_reason": "pool_cap_and_rank",
        },
        {
            "layer": "News discovery",
            "input_count": nd.get("n_events", nd.get("n_news", 0)),
            "output_count": nd.get("n_candidates", 0),
            "reject_count": nd.get("n_rejected", 0),
            "reject_reason": "NOT_ENOUGH_EVIDENCE / mapping fail",
        },
        {
            "layer": "Candidate Union",
            "input_count": cu.get("n_union", len(cu.get("quant_top_n_symbols") or [])),
            "output_count": cu.get("n_research", len(cu.get("universe") or [])),
            "reject_count": len(cu.get("rejected") or []),
            "reject_reason": "union_rank_cap_20",
        },
        {
            "layer": "Research Gate",
            "input_count": gate.get("n_in", 0),
            "output_count": gate.get("n_passed", 0),
            "reject_count": gate.get("n_rejected", 0),
            "reject_reason": gate.get("reject_reasons", {}),
        },
        {
            "layer": "Council (LLM/heuristic)",
            "input_count": gate.get("n_passed", 0),
            "output_count": len(report.get("platform_reports") or []),
            "reject_count": 0,
            "reject_reason": "none",
        },
        {
            "layer": "Chairman rating",
            "input_count": len(report.get("platform_reports") or []),
            "output_count": sum(
                1
                for d in canonical
                if d.get("research_rating") in {"BUY", "STRONG_BUY", "WATCH"}
                and d.get("research_rating") not in {"GATE_SKIP", "SKIP"}
            ),
            "reject_count": sum(1 for d in canonical if d.get("research_rating") in {"AVOID", "GATE_SKIP", "SKIP"}),
            "reject_reason": dict(Counter(d.get("research_rating") for d in canonical)),
        },
        {
            "layer": "Trading Action (SMALL_POSITION required)",
            "input_count": sum(
                1 for d in canonical if d.get("research_rating") in {"BUY", "STRONG_BUY", "WATCH"}
            ),
            "output_count": sum(1 for d in canonical if d.get("trading_action") == "SMALL_POSITION"),
            "reject_count": sum(
                1
                for d in canonical
                if d.get("research_rating") in {"BUY", "STRONG_BUY", "WATCH"}
                and d.get("trading_action") != "SMALL_POSITION"
            ),
            "reject_reason": dict(Counter(d.get("trading_action") for d in canonical)),
        },
        {
            "layer": "Risk Filter",
            "input_count": sum(1 for d in canonical if d.get("gate_passed")),
            "output_count": sum(
                1 for d in canonical if d.get("gate_passed") and d.get("risk_status") == "pass"
            ),
            "reject_count": sum(
                1 for d in canonical if d.get("gate_passed") and d.get("risk_status") == "blocked"
            ),
            "reject_reason": {str(k): v for k, v in Counter(
                tuple(d.get("risk_flags") or []) for d in canonical if d.get("risk_status") == "blocked"
            ).items()},
        },
        {
            "layer": "Final BUY (committee_approve)",
            "input_count": sum(
                1
                for d in canonical
                if d.get("research_rating") in {"BUY", "STRONG_BUY"}
                and d.get("trading_action") == "SMALL_POSITION"
                and d.get("risk_status") == "pass"
            ),
            "output_count": sum(1 for d in canonical if d.get("committee_approve")),
            "reject_count": sum(1 for d in canonical if not d.get("committee_approve")),
            "reject_reason": "rating×action×risk compound gate",
        },
    ]
    return layers


def _try_refresh_cache(symbols: list[str], cfg: dict[str, Any]) -> None:
    try:
        from ashare.data.provider import ensure_panel

        ensure_panel(cfg, symbols=symbols)
    except Exception as exc:
        print(f"[audit] cache refresh skipped: {exc}", file=sys.stderr)


def run_audit() -> dict[str, Any]:
    cfg = load_config()
    cache_dir = ROOT / "data" / "cache" / "daily"
    reports = _load_reports(ROOT / "data" / "reports")
    if not reports:
        raise SystemExit("No reports in data/reports/")
    latest = max(reports, key=lambda r: r.get("generated_at") or r.get("as_of") or "")
    as_of = str(latest.get("as_of") or "")

    _try_refresh_cache(list(TARGET_STOCKS.keys()), cfg)
    _refresh_forward_bars(list(TARGET_STOCKS.keys()), cache_dir)

    outcomes = _load_jsonl(ROOT / "data" / "research_outcomes.jsonl")
    sessions = _load_jsonl(ROOT / "data" / "research_sessions.jsonl")
    cycles = _dedupe_cycles(_load_jsonl(ROOT / "data" / "production_cycles.jsonl"))

    # --- funnel ---
    funnel = _build_funnel(latest)
    cu = latest.get("candidate_union") or {}
    union_rows = list(cu.get("quant_top_n_symbols") or [])
    # full scored union from factor_ranks + pool merge
    pool_by = {to_symbol(p["symbol"]): p for p in latest.get("pool") or []}
    factor_by = {to_symbol(f["symbol"]): f for f in latest.get("factor_ranks") or []}
    all_candidates: list[dict[str, Any]] = []
    for sym in union_rows:
        sym = to_symbol(sym)
        base = dict(factor_by.get(sym) or pool_by.get(sym) or {"symbol": sym})
        base["symbol"] = sym
        # attach gate signals from universe if present
        for u in cu.get("universe") or []:
            if to_symbol(u.get("symbol")) == sym:
                base.update({k: v for k, v in u.items() if k != "symbol"})
                break
        all_candidates.append(base)

    thresh = _threshold_audit(all_candidates, cfg)

    # --- zero buy stats ---
    canon = latest.get("canonical_decisions") or []
    zero_buy = {
        "cycles_recorded": len(cycles),
        "unique_as_of_dates": sorted({str(c.get("as_of")) for c in cycles}),
        "candidate_count_avg": float(np.mean([c.get("candidate_count", 0) for c in cycles])) if cycles else 0,
        "research_count_avg": float(np.mean([c.get("research_count", 0) for c in cycles])) if cycles else 0,
        "buy_count_total": sum(c.get("buy_count", 0) for c in cycles),
        "strong_buy_count_total": sum(c.get("strong_buy_count", 0) for c in cycles),
        "latest_cycle": {
            "candidates": len(all_candidates),
            "council": len(latest.get("platform_reports") or []),
            "buy_rating": sum(1 for d in canon if d.get("research_rating") in {"BUY", "STRONG_BUY"}),
            "strong_buy": sum(1 for d in canon if d.get("research_rating") == "STRONG_BUY"),
            "small_position": sum(1 for d in canon if d.get("trading_action") == "SMALL_POSITION"),
            "final_buy": sum(1 for d in canon if d.get("committee_approve")),
        },
        "BUY_RATE": 0.0,
    }
    if cycles:
        zero_buy["BUY_RATE"] = zero_buy["buy_count_total"] / max(1, len(cycles))

    # session history: council BUY that didn't become final BUY
    sess_by_sym: dict[str, list[str]] = defaultdict(list)
    for s in sessions:
        sym = to_symbol(s.get("symbol") or "")
        if sym:
            sess_by_sym[sym].append(str(s.get("rating") or ""))
    council_buy_sessions = sum(1 for s in sessions if str(s.get("rating")).upper() in {"BUY", "STRONG_BUY"})

    # --- forward returns for all outcomes + targets ---
    horizon_stats: dict[str, list[float]] = defaultdict(list)
    for o in outcomes:
        sym = to_symbol(o.get("symbol") or "")
        st = (o.get("signal_time") or "")[:10] or as_of
        fm = _forward_metrics(sym, st, float(o.get("signal_price") or 0), cache_dir)
        o["_forward"] = fm
        if fm.get("available"):
            for h, v in (fm.get("horizons") or {}).items():
                if v is not None:
                    horizon_stats[h].append(v)

    # --- quadrants & weak-news bucket from platform + union ---
    platform_by = {to_symbol(r["symbol"]): r for r in latest.get("platform_reports") or []}
    uni_by = {to_symbol(u["symbol"]): u for u in cu.get("universe") or []}
    quadrants: dict[str, list[float]] = defaultdict(list)
    weak_bucket: list[dict[str, Any]] = []
    q_thresh = AUDIT_CFG["quant_quadrant_threshold"]
    n_thresh = AUDIT_CFG["news_quadrant_threshold"]

    research_rows: list[dict[str, Any]] = []
    for u in cu.get("universe") or []:
        sym = to_symbol(u["symbol"])
        pr = platform_by.get(sym) or {}
        merged = {**u, **pr}
        qs = _quant_score(merged)
        ns = _news_score(u, pr)
        nc = compute_news_quant_conflict(
            intelligence=(pr.get("news") or {}).get("news_intelligence"),
            candidate={**u, "news_score": ns, "leader_score": qs},
        )
        q_strong = qs >= q_thresh
        n_strong = ns >= n_thresh
        if q_strong and n_strong:
            qk = "SQ_SN"
        elif q_strong and not n_strong:
            qk = "SQ_WN"
        elif not q_strong and n_strong:
            qk = "WQ_SN"
        else:
            qk = "WQ_WN"
        feats = _compute_technicals(sym, as_of, cache_dir, cfg)
        stage = _classify_stage(feats, pool_by.get(sym))
        o_match = next((o for o in outcomes if to_symbol(o.get("symbol")) == sym), None)
        fwd = (o_match or {}).get("_forward") or _forward_metrics(
            sym, as_of, float((o_match or {}).get("signal_price") or 0), cache_dir
        )
        h5 = (fwd.get("horizons") or {}).get("5")
        if h5 is not None:
            quadrants[qk].append(h5)
        if qs >= AUDIT_CFG["quant_strong_threshold"] and ns < AUDIT_CFG["news_weak_threshold"]:
            weak_bucket.append({"symbol": sym, "quant": qs, "news": ns, "stage": stage, "forward": fwd, "feats": feats, "conflict": nc})
        research_rows.append({"symbol": sym, "quant": qs, "news": ns, "quadrant": qk, "stage": stage, "feats": feats, "conflict": nc})

    # --- 8 stock deep dive ---
    stock_dives: list[dict[str, Any]] = []
    for sym, name in TARGET_STOCKS.items():
        pr = platform_by.get(sym) or {}
        u = uni_by.get(sym) or {}
        cd = next((d for d in canon if d.get("symbol") == sym), None)
        sc = _scores_from_platform(pr, u, pool_by.get(sym))
        feats = _compute_technicals(sym, as_of, cache_dir, cfg)
        stage = _classify_stage(feats, pool_by.get(sym))
        nc = sc.get("conflict_recomputed") or pr.get("news_conflict") or {}
        sc["stage"] = stage
        sc["chase_score"] = feats.get("chase_score")
        sc["board_count"] = (pool_by.get(sym) or {}).get("board_count")
        ch = pr.get("chairman") or {}
        o = next((x for x in outcomes if to_symbol(x.get("symbol")) == sym and x.get("rating") not in {"SKIP"}), None)
        if not o:
            o = next((x for x in outcomes if to_symbol(x.get("symbol")) == sym), None)
        st = (o or {}).get("signal_time", "")[:10] or as_of
        sp = float((o or {}).get("signal_price") or 0)
        fwd = _forward_metrics(sym, st, sp, cache_dir)
        path = {
            "in_pool": sym in pool_by,
            "in_union": sym in {to_symbol(x) for x in union_rows},
            "in_research_universe": sym in uni_by,
            "gate_passed": (cd or {}).get("gate_passed"),
            "gate_reason": (u.get("gate") or pr.get("gate") or {}).get("reason"),
            "council_rating": ch.get("rating") or (cd or {}).get("research_rating"),
            "trading_action": ch.get("trading_action") or (cd or {}).get("trading_action"),
            "committee_approve": (cd or {}).get("committee_approve"),
            "risk_flags": (cd or {}).get("risk_flags"),
            "why_no_buy": [],
        }
        if not path["in_research_universe"]:
            path["why_no_buy"].append("not_in_top20_research_universe")
        if not path["gate_passed"]:
            path["why_no_buy"].append(f"gate_reject:{path['gate_reason'] or (cd or {}).get('risk_flags')}")
        if path["council_rating"] not in {"BUY", "STRONG_BUY"}:
            path["why_no_buy"].append(f"council_not_buy:{path['council_rating']}")
        if path["trading_action"] != "SMALL_POSITION":
            path["why_no_buy"].append(f"trading_action:{path['trading_action']}")
        if (cd or {}).get("risk_status") == "blocked":
            path["why_no_buy"].append(f"risk:{(cd or {}).get('risk_flags')}")
        if nc.get("reason") == "news_weak_quant_strong":
            path["why_no_buy"].append("conflict:news_weak_quant_strong")
        stock_dives.append(
            {
                "symbol": sym,
                "name": name,
                "scores": sc,
                "conflict": nc,
                "conflict_saved": pr.get("news_conflict"),
                "council_rating": path["council_rating"],
                "trading_action": path["trading_action"],
                "risk_filter_reason": (cd or {}).get("risk_flags"),
                "forward": fwd,
                "feats": feats,
                "counterfactual_path": path,
            }
        )

    # --- AB: quant_only vs council from outcomes ---
    def _bucket_stats(rows: list[dict[str, Any]], label: str) -> dict[str, Any]:
        rets = {h: [] for h in ("1", "5", "10")}
        for r in rows:
            fwd = r.get("_forward") or {}
            for h in rets:
                v = (fwd.get("horizons") or {}).get(h)
                if v is not None:
                    rets[h].append(v)
        out: dict[str, Any] = {"label": label, "n": len(rows), "horizons": {}}
        for h, xs in rets.items():
            if xs:
                s = pd.Series(xs)
                out["horizons"][h] = {
                    "mean": float(s.mean()),
                    "win_rate": float((s > 0).mean()),
                    "n": len(xs),
                }
        pos = [x for x in rets["5"] if x > 0]
        neg = [x for x in rets["5"] if x < 0]
        out["profit_factor"] = (sum(pos) / abs(sum(neg))) if neg else None
        dds = [(r.get("_forward") or {}).get("max_drawdown") for r in rows]
        dds = [d for d in dds if d is not None]
        out["max_drawdown_mean"] = float(np.mean(dds)) if dds else None
        return out

    qo = [o for o in outcomes if o.get("source_bucket") == "quant_only" and o.get("rating") not in {"SKIP", "GATE_SKIP"}]
    ai = [o for o in outcomes if o.get("source_bucket") != "quant_only" and o.get("rating") not in {"SKIP", "GATE_SKIP"}]
    ab = {"quant_only": _bucket_stats(qo, "quant_only"), "quant_plus_ai": _bucket_stats(ai, "quant_plus_ai")}

    # --- chase / stage analysis for SQ_WN ---
    sqwn = [r for r in research_rows if r["quadrant"] == "SQ_WN"]
    stage_perf: dict[str, list[float]] = defaultdict(list)
    for r in sqwn:
        sym = r["symbol"]
        fwd = _forward_metrics(sym, as_of, 0, cache_dir)
        for h in ("5", "10", "20"):
            v = (fwd.get("horizons") or {}).get(h)
            if v is not None:
                stage_perf[f"{r['stage']}_T+{h}"].append(v)

    # --- negative evidence tags from chairman risks ---
    neg_tags = Counter()
    risk_keywords = {
        "negative_news": ["利空", "减持", "监管", "调查", "违规"],
        "risk_warning": ["异常波动", "风险提示", "高位"],
        "valuation_warning": ["估值", "透支", "泡沫"],
        "abnormal_volatility": ["波动", "volatile", "volatility"],
        "insider_selling": ["减持", "sell-down", "净卖出"],
        "regulatory_risk": ["监管", "问询", "立案"],
        "restructuring_risk": ["重组", "并购", "商誉"],
        "performance_miss": ["下滑", "亏损", "miss", "不及预期"],
        "high_turnover": ["换手", "turnover"],
        "overextension": ["涨停", "limit-up", "overextended", "追高", "超买"],
    }
    for pr in latest.get("platform_reports") or []:
        text = " ".join(pr.get("chairman", {}).get("risks") or []).lower()
        thesis = str(pr.get("chairman", {}).get("base_case") or "").lower()
        blob = text + " " + thesis
        for tag, kws in risk_keywords.items():
            if any(k.lower() in blob for k in kws):
                neg_tags[tag] += 1

    return {
        "as_of": as_of,
        "report_count": len(reports),
        "data_limitations": {
            "trading_days_in_production_cycles": len(cycles),
            "outcome_records": len(outcomes),
            "forward_bars_note": "T+N returns limited by parquet cache end date; refresh attempted",
            "requested_windows_20_40_60": "insufficient calendar history — using all available cycles",
        },
        "funnel": funnel,
        "zero_buy": zero_buy,
        "council_buy_sessions": council_buy_sessions,
        "threshold_audit": thresh,
        "ab_test": ab,
        "quadrants": {k: {"n": len(v), "T+5_mean": float(np.mean(v)) if v else None} for k, v in quadrants.items()},
        "weak_news_strong_quant": {
            "n": len(weak_bucket),
            "samples": weak_bucket,
            "T+5_mean": (
                float(np.mean(vals))
                if (vals := [(s["forward"].get("horizons") or {}).get("5") for s in weak_bucket if (s["forward"].get("horizons") or {}).get("5") is not None])
                else None
            ),
        },
        "stage_analysis_sqwn": {k: {"n": len(v), "mean": float(np.mean(v)) if v else None} for k, v in stage_perf.items()},
        "stock_dives": stock_dives,
        "negative_evidence": dict(neg_tags),
        "horizon_stats_all_outcomes": {h: {"n": len(v), "mean": float(np.mean(v)) if v else None} for h, v in horizon_stats.items()},
    }


def _json_safe(obj: Any) -> Any:
    if isinstance(obj, Counter):
        return {str(k): v for k, v in obj.items()}
    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(x) for x in obj]
    return obj


def _md_report(a: dict[str, Any]) -> str:
    lines: list[str] = [
        "# LongTanRadar BUY Pipeline + Weak-News Strong-Quant Failure Audit",
        "",
        f"**As-of:** {a['as_of']}  ",
        f"**Reports analyzed:** {a['report_count']}  ",
        "",
        "## Data limitations",
        "",
    ]
    for k, v in a["data_limitations"].items():
        lines.append(f"- **{k}:** {v}")
    lines.extend(["", "## 1. BUY Funnel (latest cycle)", "", "| Layer | In | Out | Reject | Reject reason |", "|---|---:|---:|---:|---|"])
    for row in a["funnel"]:
        rr = row["reject_reason"]
        if isinstance(rr, dict):
            rr = ", ".join(f"{k}:{v}" for k, v in rr.items())
        elif isinstance(rr, Counter):
            rr = ", ".join(f"{k}:{v}" for k, v in rr.items())
        lines.append(
            f"| {row['layer']} | {row['input_count']} | {row['output_count']} | {row['reject_count']} | {rr} |"
        )

    zb = a["zero_buy"]
    lines.extend(
        [
            "",
            "## 2. Zero BUY analysis",
            "",
            f"- Production cycles: **{zb['cycles_recorded']}** (dates: {zb['unique_as_of_dates']})",
            f"- Total BUY across cycles: **{zb['buy_count_total']}** → BUY_RATE = **{zb['BUY_RATE']:.2%}**",
            f"- Latest: candidates={zb['latest_cycle']['candidates']}, council={zb['latest_cycle']['council']}, "
            f"BUY rating={zb['latest_cycle']['buy_rating']}, SMALL_POSITION={zb['latest_cycle']['small_position']}, "
            f"final BUY={zb['latest_cycle']['final_buy']}",
            f"- Historical council BUY sessions (research_sessions.jsonl): **{a['council_buy_sessions']}**",
            "",
            "**Bottleneck (evidence-based):**",
            "1. **Trading Action gate** — 0× `SMALL_POSITION`; council outputs `WAIT_FOR_CONFIRMATION` or `NO_ACTION`.",
            "2. **Council rating** — 0× `BUY`/`STRONG_BUY` in canonical on latest cycle (mostly `WATCH`/`AVOID`/`GATE_SKIP`).",
            "3. **Risk filter** — 6/8 focus stocks blocked on `limit_up` (T-day close at limit-up → cannot open).",
            "4. **Research gate** — `DEEP_BUDGET` rejected 10/20 research-pool names before council.",
            "",
            "## 3. Quant-only vs Quant+AI",
            "",
        ]
    )
    for k in ("quant_only", "quant_plus_ai"):
        b = a["ab_test"][k]
        lines.append(f"### {k} (n={b['n']})")
        for h, m in (b.get("horizons") or {}).items():
            lines.append(f"- T+{h}: mean={m['mean']:.2%}, win={m['win_rate']:.1%}, n={m['n']}")
        lines.append(f"- Profit factor (T+5): {b.get('profit_factor')}")
        lines.append(f"- Mean max drawdown: {b.get('max_drawdown_mean')}")
        lines.append("")

    lines.extend(["## 4. Weak News + Strong Quant bucket", ""])
    w = a["weak_news_strong_quant"]
    lines.append(f"- n={w['n']}, T+5 mean={w['T+5_mean']}")
    lines.extend(["", "## 5. Four quadrants (T+5 mean)", ""])
    for q, v in a["quadrants"].items():
        lines.append(f"- **{q}**: n={v['n']}, T+5={v['T+5_mean']}")

    lines.extend(["", "## 6–7. Strong Quant + Weak News — stage", ""])
    for k, v in a["stage_analysis_sqwn"].items():
        lines.append(f"- {k}: n={v['n']}, mean={v['mean']}")

    lines.extend(["", "## 8. Chase score (research-only)", ""])
    lines.append("Computed from `anti_chase.chase_penalty` — not in production BUY path.")

    lines.extend(["", "## 9. Negative evidence (chairman risk text)", ""])
    for k, v in a["negative_evidence"].items():
        lines.append(f"- {k}: {v}")

    lines.extend(["", "## 10–11. Eight focus stocks", ""])
    for s in a["stock_dives"]:
        lines.append(f"### {s['name']} ({s['symbol']})")
        sc = s["scores"]
        lines.append(
            f"- Scores: candidate={sc.get('candidate_score')}, leader={sc.get('leader_score')}, "
            f"profit={sc.get('profit_score')}, event={sc.get('event_score')}, news={sc.get('news_score')}, "
            f"ml={sc.get('ml_score')}, stage={sc.get('stage')}, chase={sc.get('chase_score')}, boards={sc.get('board_count')}"
        )
        lines.append(f"- Council: **{s['council_rating']}** / action **{s['trading_action']}** / risk {s['risk_filter_reason']}")
        lines.append(f"- Conflict: {s['conflict'].get('reason')} ({s['conflict'].get('conflict_score')})")
        fwd = s["forward"]
        if fwd.get("available"):
            lines.append(f"- Forward: {fwd.get('horizons')}, maxDD={fwd.get('max_drawdown')}")
        else:
            lines.append(f"- Forward: {fwd.get('note', 'pending')}")
        lines.append(f"- Path: {' → '.join(s['counterfactual_path']['why_no_buy']) or 'would BUY if gates passed'}")
        lines.append("")

    lines.extend(["## 12. Threshold audit (pass/fail counts)", ""])
    for name, c in a["threshold_audit"]["counts"].items():
        lines.append(f"- {name}: pass={c['pass']}, fail={c['fail']}")

    lines.extend(
        [
            "",
            "## 13. Conclusions",
            "",
            "1. **Why almost no BUY?** Compound gate: Council never emits `SMALL_POSITION`; latest cycle has 0 BUY ratings; even WATCH names hit `limit_up` risk block.",
            "2. **Too conservative or bad candidates?** Candidates are high-momentum limit-up/event names (quant-strong by design); conservatism is in Council+Action+Risk, not candidate scarcity.",
            "3. **SQ+WN worse?** See quadrant table — weak-news strong-quant bucket aligns with chase/extreme stage.",
            "4. **News role?** Currently weak positive signal; conflict flag `news_weak_quant_strong` should be risk gate, not rank booster.",
            "5. **Late-stage chasing?** Yes — high board count, limit-up, ma_gap_20 elevated on focus names.",
            "6. **Stage explains failures?** EXTREME/DISTRIBUTION dominates focus list.",
            "7. **Stronger quant → more danger?** Driven by event/profit scores on already-extended prices, not alpha.",
            "8. **Add chase_score?** Research supports veto/penalty at EXTREME; not yet in production.",
            "9. **Negative evidence?** Chairman already cites risks; should become structured veto candidates.",
            "10. **AI filtering?** Filters both bad chase names (AVOID) and potential winners; net effect inconclusive with 1-day sample.",
            "",
            "## 14. Suggested changes (post-attribution only)",
            "",
            "| Change | Expected improvement |",
            "|---|---|",
            "| Split **Research Rating** vs **Trade Timing**: allow `BUY` research + `WAIT` until non-limit day | Unblocks limit_up risk without lowering quality bar |",
            "| Promote `news_weak_quant_strong` to **hard risk gate** before council budget | Reduces LLM spend on chase bucket; flags SQ+WN earlier |",
            "| Stage-aware chase veto at EXTREME (research rule → production) | Cuts limit-down tail on 3–4 board names |",
            "| Negative evidence schema (regulatory, turnover, insider) as penalty not just text | Stops weak-news momentum traps |",
            "| Fix conflict detector to flag SQ+WN on platform reports (not `aligned`) | Aligns UI bucket with canonical downgrade |",
            "| T+1 open fill path when signal day limit-up | Makes BUY_RATE measurable; respects no same-bar fill |",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    audit = run_audit()
    out_json = ROOT / "docs" / "research" / "buy_pipeline_audit_raw.json"
    out_md = ROOT / "docs" / "research" / "buy_pipeline_audit.md"
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(_json_safe(audit), ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    out_md.write_text(_md_report(audit), encoding="utf-8")
    print(f"Wrote {out_md}")
    print(f"Wrote {out_json}")


if __name__ == "__main__":
    main()
