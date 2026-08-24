from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ashare.data.names import attach_names
from ashare.data.provider import ensure_panel
from ashare.db.pg import database_url_from_env, get_engine
from ashare.db.redis_client import cache_get, cache_set, redis_url_from_env
from ashare.factors.score import score_candidates
from ashare.pool.builder import build_leader_pool
from ashare.symbols import to_symbol

logger = logging.getLogger("ashare.services.research")


def _panel_asof(panel: dict, as_of) -> dict[str, Any]:
    import pandas as pd

    bars: dict[str, Any] = {}
    hist: dict[str, Any] = {}
    cutoff = pd.Timestamp(as_of)
    for sym, df in panel.items():
        sub = df[pd.to_datetime(df["date"]) <= cutoff]
        if sub.empty:
            continue
        hist[sym] = sub
        row = sub.iloc[-1]
        from ashare.backtest.engine import row_to_bar

        bars[sym] = row_to_bar(row)
    return {"bars": bars, "hist": hist}


def _reports_dir(cfg: dict[str, Any]) -> Path:
    path = Path(cfg["_root"]) / "data" / "reports"
    path.mkdir(parents=True, exist_ok=True)
    return path


def persist_report(cfg: dict[str, Any], payload: dict[str, Any]) -> Path:
    folder = _reports_dir(cfg)
    latest = folder / "latest.json"
    latest.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    as_of = str(payload.get("as_of") or "na")
    dated = folder / f"{as_of}.json"
    dated.write_text(latest.read_text(encoding="utf-8"), encoding="utf-8")
    md = folder / "latest.md"
    md.write_text(_to_markdown(payload), encoding="utf-8")
    return latest


def _to_markdown(payload: dict[str, Any]) -> str:
    lines = [
        f"# 龙头股投委会研报 · {payload.get('as_of')}",
        "",
        payload.get("roundtable", {}).get("summary") or "",
        "",
        f"- 股票池规模：{payload.get('universe_size')}",
        f"- 因子打分：{payload.get('scored')}",
        f"- 圆桌来源：{payload.get('roundtable', {}).get('source')}",
        f"- 模型："
        + ", ".join(
            f"{m.get('role')}={m.get('model')}"
            for m in (payload.get("roundtable", {}).get("models_used") or [])
        ),
        "",
        "## 交叉论证",
    ]
    for r in payload.get("roundtable", {}).get("roles") or []:
        lines.append(f"### {r.get('name') or r.get('id')}（{r.get('stance')} · 模型 {r.get('model') or '—'}）")
        for p in r.get("points") or []:
            lines.append(f"- {p}")
        if r.get("falsify"):
            lines.append(f"- 证伪：{r.get('falsify')}")
        lines.append("")
    for d in payload.get("roundtable", {}).get("debate") or []:
        lines.append(f"- {d.get('from')} → {d.get('to')}：{d.get('point')}")
    lines += ["", "## 结论"]
    for p in payload.get("picks") or []:
        lines.append(
            f"### {p.get('name') or ''} {p.get('symbol')} · {p.get('committee_verdict')}"
        )
        lines.append(p.get("committee_thesis") or p.get("why") or "")
        lines.append(f"风险：{p.get('committee_risks') or '—'}")
        lines.append(f"观察窗口：{p.get('committee_horizon') or 'T+1'}")
        lines.append("")
    notes = payload.get("roundtable", {}).get("replay_notes")
    if notes:
        lines += ["## 复盘要点", notes]
    return "\n".join(lines) + "\n"


def run_research(cfg: dict[str, Any], top_n: int | None = None) -> dict[str, Any]:
    """因子库打分 + 事件/利润断层池 + AI 圆桌，输出可复盘研报。"""
    from ashare.ai.cost_tracker import get_cost_tracker
    from ashare.ai.roundtable import run_roundtable
    from ashare.candidate import CandidateEngine
    from ashare.config_loaders import load_yaml_config
    from ashare.portfolio import RiskFilterEngine, market_regime
    from ashare.research.progress import get_research_progress
    from ashare.research.session import ResearchSessionEngine

    progress = get_research_progress()
    cycle_id = f"research_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    get_cost_tracker(cfg).begin_cycle(cycle_id)

    with progress.step("pool", "构建龙头/事件池", note="akshare 涨停/强势/利润断层"):
        pool = build_leader_pool(cfg)
    cfg["_last_screen"] = pool
    symbols = [to_symbol(s) for s in (pool.get("symbols") or [])]
    progress.log("pool", f"池规模 {len(symbols)}", detail=pool.get("sources"))
    if not symbols:
        raise RuntimeError("龙头/事件股票池为空 — 检查网络或 pool 配置")

    try:
        from ashare.data.names import load_name_map, save_name_map

        names = load_name_map(cfg)
        for row in pool.get("candidates") or []:
            if row.get("symbol") and row.get("name"):
                names[to_symbol(row["symbol"])] = str(row["name"])
        save_name_map(cfg, names)
    except Exception as exc:  # noqa: BLE001
        logger.debug("save pool names failed: %s", exc)

    with progress.step("panel", "加载/刷新日线缓存", note="Parquet + akshare"):
        panel = ensure_panel(cfg, symbols)
    progress.log("panel", f"日线 panel {len(panel)} 只")
    if not panel:
        raise RuntimeError("No market data — run fetch first / check network")

    import pandas as pd

    last_dates = []
    for df in panel.values():
        if not df.empty:
            last_dates.append(pd.to_datetime(df["date"]).max())
    as_of = max(last_dates).date()
    as_of_dt = datetime(as_of.year, as_of.month, as_of.day, 23, 59, 59, tzinfo=timezone.utc)
    news_discovery: dict[str, Any] = {"available": False, "note": "not_run"}
    try:
        from ashare.news.opportunity import NewsOpportunityEngine

        with progress.step("news_discovery", "新闻发现", note="多源抓取 + 事件抽取"):
            news_discovery = NewsOpportunityEngine(cfg).discover(as_of=as_of_dt, persist=True)
        progress.log(
            "news_discovery",
            f"候选 {news_discovery.get('n_candidates', 0)} / 拒绝 {news_discovery.get('n_rejected', 0)}",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("news discovery skipped: %s", exc)
        news_discovery = {
            "available": False,
            "news_data_incomplete": True,
            "error": str(exc)[:300],
            "news_candidates": [],
            "events": [],
            "rejected": [],
        }
    extra: list[str] = []
    for c in news_discovery.get("news_candidates") or []:
        try:
            s = to_symbol(c.get("symbol"))
        except Exception:  # noqa: BLE001
            continue
        if s and s not in panel:
            extra.append(s)
    if extra:
        try:
            panel.update(ensure_panel(cfg, extra))
        except Exception as exc:  # noqa: BLE001
            logger.warning("news candidate bars failed: %s", exc)
    # Phase 6: annotate discovery candidates with price reaction (warning only)
    try:
        from ashare.research.price_reaction import annotate_news_candidate_price

        annotated = []
        for c in news_discovery.get("news_candidates") or []:
            try:
                annotated.append(annotate_news_candidate_price(c, panel, as_of=str(as_of)))
            except Exception:  # noqa: BLE001
                annotated.append(c)
        news_discovery["news_candidates"] = annotated
    except Exception as exc:  # noqa: BLE001
        logger.warning("price reaction annotate skipped: %s", exc)
    snap = _panel_asof(panel, as_of)
    meta_by = {to_symbol(c["symbol"]): c for c in (pool.get("candidates") or [])}

    rows: list[dict[str, Any]] = []
    for sym, bar in snap["bars"].items():
        if bar.is_st or bar.is_halt:
            continue
        meta = dict(meta_by.get(to_symbol(sym)) or {"symbol": to_symbol(sym)})
        hist = snap["hist"][sym]
        rows.append({**meta, "symbol": to_symbol(sym), "hist": hist, "close": float(bar.close)})

    scored = score_candidates(rows, cfg)
    n = int(top_n or cfg.get("strategy", {}).get("top_n", 5))
    shortlist = scored[: max(1, n)]
    rt_cfg = (cfg.get("ai") or {})
    roundtable_mode = str(rt_cfg.get("roundtable_mode") or "sampled").lower()
    from ashare.research.benchmark import should_run_roundtable

    run_rt, rt_reason = should_run_roundtable(cfg, as_of=as_of.date() if hasattr(as_of, "date") else None)
    run_rt = run_rt and bool(rt_cfg.get("roundtable", True)) and roundtable_mode != "disabled"
    if run_rt and shortlist:
        with progress.step("roundtable", "圆桌 Benchmark", note=rt_reason):
            roundtable = run_roundtable(cfg, shortlist)
        roundtable["benchmark_only"] = True
        roundtable["controls_trading"] = False
        roundtable["schedule_reason"] = rt_reason
        progress.log(
            "roundtable",
            f"来源 {roundtable.get('source')} · 角色 {len(roundtable.get('roles') or [])} · {rt_reason}",
            detail=roundtable.get("models_used"),
        )
    else:
        roundtable = {
            "source": "disabled",
            "summary": f"圆桌跳过（{rt_reason}）",
            "roles": [],
            "debate": [],
            "benchmark_only": True,
            "controls_trading": False,
            "schedule_reason": rt_reason,
        }
    # Legacy roundtable never drives trading — canonical decisions only (V5 Phase 1).
    picks: list[dict[str, Any]] = []
    canonical_decisions: list[dict[str, Any]] = []

    # --- Platform v2 path (Candidate → ML rank hint → Council sessions) ---
    platform_reports: list[dict[str, Any]] = []
    uni: dict[str, Any] = {}
    outcome_pack: dict[str, Any] = {"available": False, "note": "no_platform_reports"}
    gate_summary: dict[str, Any] = {}
    research_yaml = load_yaml_config(cfg, "research")
    use_platform = bool(research_yaml.get("enabled", True))
    if use_platform:
        try:
            cand_eng = CandidateEngine(cfg)
            with progress.step("candidate", "候选 Union + 逐股新闻", note="最多 20 只 × 3 源"):
                uni = cand_eng.build_research_universe(
                    panel=panel,
                    pool=pool,
                    news_discovery=news_discovery,
                    as_of=as_of_dt.isoformat(),
                )
            progress.log(
                "candidate",
                f"Union {uni.get('n_union')} → 研究池 {len(uni.get('research_universe') or [])}",
            )
            regime = market_regime(
                panel_mom20=[
                    float((r.get("factors") or {}).get("momentum_20d") or 0)
                    for r in uni.get("research_universe") or []
                ]
            )
            for r in uni.get("research_universe") or []:
                r["market_regime"] = regime
            session = ResearchSessionEngine(cfg)
            with progress.step("council", "Council 多角色研究", note="串行逐股 · 角色内并行"):
                platform_reports = session.run_pool(uni.get("research_universe") or [], panel=panel)
            gate_summary = session.gate_summary()
            progress.log(
                "council",
                f"报告 {len(platform_reports)} · LLM {gate_summary.get('llm_budget')}",
            )
            from ashare.research.canonical_decision import (
                DECISION_SOURCE_PLATFORM,
                apply_portfolio_weights,
                build_canonical_decisions,
                canonical_to_picks,
            )

            risk = RiskFilterEngine(cfg)
            uni_by_sym = {to_symbol(r["symbol"]): r for r in (uni.get("research_universe") or [])}
            src_map = {sym: r.get("candidate_sources") for sym, r in uni_by_sym.items()}
            for rep in platform_reports:
                sym = to_symbol(rep.get("symbol") or "")
                if sym and not rep.get("candidate_sources"):
                    rep["candidate_sources"] = src_map.get(sym) or []
            with progress.step("decision", "Canonical 决策 + 风控", note="单一交易真相源"):
                canonical_decisions = build_canonical_decisions(
                    platform_reports,
                    as_of=as_of.isoformat(),
                    universe_by_sym=uni_by_sym,
                    bars_by_sym=snap["bars"],
                    risk_engine=risk,
                    decision_source=DECISION_SOURCE_PLATFORM,
                )
                canonical_decisions = apply_portfolio_weights(canonical_decisions, cfg)
                picks = canonical_to_picks(canonical_decisions)
            progress.log("decision", f"买入 {sum(1 for d in canonical_decisions if d.get('committee_approve'))} 只")
            # Phase 7: outcome attribution by discovery source (descriptive only)
            try:
                from ashare.research.benchmark import resolve_dual_benchmark_pack
                from ashare.research.tracking import ReviewEngine

                horizon = str(((research_yaml.get("tracking") or {}).get("attribution_horizon") or 5))
                horizons = list((research_yaml.get("tracking") or {}).get("horizons_days") or [1, 3, 5, 10, 20, 60])
                with progress.step("outcome", "归因 + 双基准 Alpha", note="Market + Selection"):
                    bench_pack = resolve_dual_benchmark_pack(cfg, panel, as_of, horizons=horizons)
                    outcome_pack = ReviewEngine(cfg).attribution_report(
                        platform_reports,
                        panel,
                        horizon=horizon,
                        market_benchmark_returns=bench_pack.get("market_returns") or None,
                        universe_benchmark_returns=bench_pack.get("universe_returns") or None,
                        benchmark_snapshot=bench_pack.get("snapshot"),
                        persist=True,
                    )
                    outcome_pack["benchmark"] = bench_pack
                    try:
                        from ashare.research.model_benchmark import build_model_benchmark
                        from ashare.research.role_ablation import compute_role_ablation

                        outcome_pack["role_ablation"] = compute_role_ablation(
                            platform_reports,
                            outcome_pack.get("outcomes") or [],
                            horizon=horizon,
                        )
                        outcome_pack["model_benchmark"] = build_model_benchmark(
                            cfg,
                            ai_incremental_alpha=outcome_pack.get("ai_incremental_alpha"),
                        )
                    except Exception as sub_exc:  # noqa: BLE001
                        logger.debug("role ablation / model benchmark skipped: %s", sub_exc)
                    try:
                        from ashare.research.factor_attribution import build_factor_attribution, persist_factor_report

                        # Optional factor IC — does not block research
                        fr = build_factor_attribution(None, cfg)
                        if not fr.get("available"):
                            fr = {"available": False, "note": "factor_panel_deferred"}
                        outcome_pack["factor_attribution"] = fr
                    except Exception as fac_exc:  # noqa: BLE001
                        logger.debug("factor attribution skipped: %s", fac_exc)
                    try:
                        from ashare.research.lab_summary import build_lab_summary
                        from ashare.research.token_efficiency import compute_token_efficiency

                        outcome_pack["token_efficiency"] = compute_token_efficiency(
                            cfg,
                            gate_summary=gate_summary,
                            routing_summary=gate_summary.get("ai_routing"),
                            outcome_pack=outcome_pack,
                        )
                        outcome_pack["lab_summary"] = build_lab_summary(outcome_pack)
                    except Exception as te_exc:  # noqa: BLE001
                        logger.debug("token efficiency skipped: %s", te_exc)
            except Exception as exc:  # noqa: BLE001
                logger.warning("outcome attribution skipped: %s", exc)
                outcome_pack = {"available": False, "error": str(exc)[:300]}
        except Exception as exc:  # noqa: BLE001
            logger.warning("platform research path failed, legacy roundtable kept: %s", exc)

    approved = [p for p in picks if p.get("committee_approve") or p.get("committee_verdict") == "buy"]
    if picks and not any(p.get("weight") for p in picks):
        w = 1.0 / len(approved) if approved else 0.0
        for p in picks:
            p["weight"] = w if (p.get("committee_approve") or p.get("committee_verdict") == "buy") else 0.0

    picks = attach_names(picks, cfg)
    if canonical_decisions:
        canonical_decisions = attach_names(canonical_decisions, cfg)
        for p in picks:
            for d in canonical_decisions:
                if d.get("symbol") == p.get("symbol"):
                    d["name"] = p.get("name")
                    d["weight"] = p.get("weight", d.get("weight", 0.0))
                    break
    payload = {
        "as_of": as_of.isoformat(),
        "strategy": "leader_roundtable",
        "picks_style": "leader",
        "universe_mode": "leader_event",
        "universe_size": len(symbols),
        "scored": len(scored),
        "screen": {
            "raw_count": pool.get("raw_count"),
            "filtered_count": pool.get("filtered_count"),
            "filters": pool.get("filters"),
            "sources": pool.get("sources"),
        },
        "pool": [
            {
                "symbol": c.get("symbol"),
                "name": c.get("name"),
                "sources": c.get("sources"),
                "board_count": c.get("board_count"),
                "profit_gap_score": c.get("profit_gap_score"),
                "event_tags": c.get("event_tags"),
                "thesis": c.get("thesis"),
            }
            for c in (pool.get("candidates") or [])[:40]
        ],
        "factor_ranks": [
            {
                "symbol": r.get("symbol"),
                "name": r.get("name"),
                "score": r.get("score"),
                "factors_z": r.get("factors_z"),
                "why": r.get("why"),
            }
            for r in scored[:20]
        ],
        "picks": picks,
        "canonical_decisions": canonical_decisions,
        "decision_chain": {
            "canonical_source": "platform_council" if canonical_decisions else "none",
            "roundtable_mode": roundtable_mode,
            "roundtable_controls_trading": False,
            "paper_trading_source": "canonical_decisions",
        },
        "news_discovery": {
            "available": news_discovery.get("available"),
            "news_data_incomplete": news_discovery.get("news_data_incomplete"),
            "provider_status": news_discovery.get("provider_status"),
            "n_news": news_discovery.get("n_news"),
            "n_events": news_discovery.get("n_events"),
            "n_candidates": news_discovery.get("n_candidates"),
            "n_rejected": news_discovery.get("n_rejected"),
            "news_candidates": (news_discovery.get("news_candidates") or [])[:40],
            "rejected": (news_discovery.get("rejected") or [])[:40],
            "note": news_discovery.get("note"),
        },
        "candidate_union": {
            "n_union": uni.get("n_union"),
            "n_research": len(uni.get("research_universe") or []),
            "universe": [
                {
                    "symbol": r.get("symbol"),
                    "name": r.get("name"),
                    "candidate_sources": r.get("candidate_sources"),
                    "candidate_score": r.get("candidate_score"),
                    "in_council": r.get("in_council"),
                    "gate": r.get("gate"),
                    "trigger": r.get("trigger"),
                    "research_hypotheses": r.get("research_hypotheses") or [],
                }
                for r in (uni.get("research_universe") or [])
            ],
            "rejected": (uni.get("rejected") or [])[:80],
            "gate": gate_summary,
        },
        "platform_reports": [
            {
                "research_id": r.get("research_id"),
                "symbol": r.get("symbol"),
                "name": r.get("name"),
                "rating": (r.get("decision") or {}).get("research_rating"),
                "action": (r.get("decision") or {}).get("action"),
                "gate": r.get("gate"),
                "candidate_sources": r.get("candidate_sources") or [],
                "research_hypotheses": r.get("research_hypotheses") or [],
                "chairman": {
                    "confidence": (r.get("chairman") or {}).get("confidence"),
                    "base_case": (r.get("chairman") or {}).get("base_case"),
                    "risks": (r.get("chairman") or {}).get("risks"),
                },
                "news": _news_from_package(r.get("news_package") or {}),
            }
            for r in platform_reports
        ],
        "research_outcomes": {
            "available": bool(outcome_pack.get("available")),
            "horizon": outcome_pack.get("horizon"),
            "n": len(outcome_pack.get("outcomes") or []),
            "outcomes": (outcome_pack.get("outcomes") or [])[:40],
            "attribution": outcome_pack.get("attribution"),
            "by_rating": outcome_pack.get("by_rating"),
            "ai_incremental_alpha": outcome_pack.get("ai_incremental_alpha"),
            "ai_topk_ablation": outcome_pack.get("ai_topk_ablation"),
            "ai_incremental_alpha_legacy": outcome_pack.get("ai_incremental_alpha_legacy"),
            "role_ablation": outcome_pack.get("role_ablation"),
            "model_benchmark": outcome_pack.get("model_benchmark"),
            "discovery_attribution": outcome_pack.get("discovery_attribution"),
            "signal_attribution": outcome_pack.get("signal_attribution"),
            "ai_council_ablation": outcome_pack.get("ai_council_ablation"),
            "calibration": outcome_pack.get("calibration"),
            "factor_attribution": outcome_pack.get("factor_attribution"),
            "benchmark": outcome_pack.get("benchmark"),
            "benchmark_snapshot": outcome_pack.get("benchmark_snapshot"),
            "portfolio_attribution": outcome_pack.get("portfolio_attribution"),
            "outcome_truth": outcome_pack.get("outcome_truth"),
            "note": outcome_pack.get("note") or outcome_pack.get("error"),
        },
        "roundtable": {
            "summary": roundtable.get("summary"),
            "source": roundtable.get("source"),
            "benchmark_only": bool(roundtable.get("benchmark_only", True)),
            "controls_trading": False,
            "replay_notes": roundtable.get("replay_notes"),
            "models_used": roundtable.get("models_used") or [],
            "chair_model": roundtable.get("chair_model"),
            "schedule_reason": roundtable.get("schedule_reason"),
            "roles": roundtable.get("roles") or [],
            "debate": roundtable.get("debate") or [],
            "reviews": [
                {
                    "symbol": r.get("symbol"),
                    "name": r.get("name"),
                    "committee_verdict": r.get("committee_verdict"),
                    "ai_approve": r.get("ai_approve"),
                    "ai_confidence": r.get("ai_confidence"),
                    "ai_rationale": r.get("ai_rationale"),
                    "committee_thesis": r.get("committee_thesis"),
                    "committee_risks": r.get("committee_risks"),
                    "committee_horizon": r.get("committee_horizon"),
                    "benchmark_only": True,
                }
                for r in (roundtable.get("reviews") or [])
            ],
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    if canonical_decisions:
        from ashare.research.canonical_decision import validate_decision_consistency

        inconsistencies = validate_decision_consistency(payload)
        payload["decision_consistency"] = {
            "ok": not inconsistencies,
            "errors": inconsistencies,
        }
        if inconsistencies:
            logger.warning("decision consistency check failed: %s", inconsistencies)
    try:
        from ashare.research.llm_budget import budget_snapshot

        cycle_cost = get_cost_tracker(cfg).cycle_summary(cycle_id)
        payload["ai_cost"] = {
            **cycle_cost,
            "budget": budget_snapshot(cycle_cost, cfg),
        }
    except Exception as exc:  # noqa: BLE001
        logger.debug("research cost summary skipped: %s", exc)
    payload["run_log"] = get_research_progress().run_log()
    with get_research_progress().step("persist", "写入研报与缓存", note="latest.json / Redis"):
        persist_report(cfg, payload)
        _persist_picks_compat(cfg, payload)
    try:
        from ashare.notification.production import record_production_cycle

        record_production_cycle(cfg, payload, cycle_id, notification_result=None)
    except Exception as exc:  # noqa: BLE001
        logger.debug("production validation skipped: %s", exc)
    try:
        from ashare.notification.service import schedule_notification_job

        schedule_notification_job(cfg, payload, cycle_id)
    except Exception as exc:  # noqa: BLE001
        logger.debug("notification schedule skipped: %s", exc)
    return payload


def _persist_picks_compat(cfg: dict[str, Any], payload: dict[str, Any]) -> None:
    from sqlalchemy import text

    rurl = redis_url_from_env(cfg)
    try:
        cache_set(rurl, "ashare:picks:latest", payload, ttl=86400)
        cache_set(rurl, "ashare:research:latest", payload, ttl=86400)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Redis cache research failed: %s", exc)

    db_url = database_url_from_env(cfg)
    try:
        eng = get_engine(db_url)
        as_of = payload["as_of"]
        with eng.begin() as conn:
            conn.execute(text("DELETE FROM picks WHERE as_of = :d"), {"d": as_of})
            for p in payload["picks"]:
                conn.execute(
                    text(
                        """
                        INSERT INTO picks (as_of, strategy, symbol, score, weight, reason)
                        VALUES (:as_of, :strategy, :symbol, :score, :weight, :reason)
                        """
                    ),
                    {
                        "as_of": as_of,
                        "strategy": payload["strategy"],
                        "symbol": p["symbol"],
                        "score": p.get("score"),
                        "weight": p.get("weight"),
                        "reason": p.get("reason") or p.get("committee_verdict"),
                    },
                )
    except Exception as exc:  # noqa: BLE001
        logger.warning("PG persist research failed: %s", exc)
        payload["persist_warning"] = str(exc)


def _news_from_package(pkg: dict[str, Any]) -> dict[str, Any]:
    return {
        "counts": pkg.get("counts"),
        "net_event_score": pkg.get("net_event_score"),
        "incomplete": pkg.get("news_data_incomplete"),
        "last_7d": pkg.get("last_7d") or [],
        "timeline": pkg.get("timeline") or [],
        "conflicts": pkg.get("conflicts") or [],
        "expectation": pkg.get("expectation"),
        "link_filter": pkg.get("link_filter"),
    }


def refresh_report_news(cfg: dict[str, Any]) -> dict[str, Any]:
    """Re-fetch per-stock news for cached platform_reports — no LLM, no council."""
    from ashare.news.engine import NewsIntelligenceEngine

    payload = latest_research(cfg)
    if not payload:
        raise RuntimeError("No research report to refresh — run research first")

    reports = list(payload.get("platform_reports") or [])
    if not reports:
        raise RuntimeError("No platform_reports in latest research")

    eng = NewsIntelligenceEngine(cfg)
    updated: list[dict[str, Any]] = []
    for rep in reports:
        sym = str(rep.get("symbol") or "")
        name = str(rep.get("name") or "")
        if not sym:
            updated.append(rep)
            continue
        try:
            pkg = eng.collect_stock(sym, name=name, persist=True)
            rep = {**rep, "news": _news_from_package(pkg)}
        except Exception as exc:  # noqa: BLE001
            logger.warning("refresh news failed for %s: %s", sym, exc)
            rep = {
                **rep,
                "news": {
                    **(rep.get("news") or {}),
                    "incomplete": True,
                    "link_filter": {"error": str(exc)},
                },
            }
        updated.append(rep)

    payload["platform_reports"] = updated
    payload["generated_at"] = datetime.now(timezone.utc).isoformat()
    payload["news_refreshed_at"] = payload["generated_at"]
    persist_report(cfg, payload)
    _persist_picks_compat(cfg, payload)
    return {
        "ok": True,
        "n_reports": len(updated),
        "generated_at": payload["generated_at"],
        "samples": [
            {
                "symbol": r.get("symbol"),
                "name": r.get("name"),
                "last_7d": (r.get("news") or {}).get("counts", {}).get("last_7d"),
                "filtered": ((r.get("news") or {}).get("link_filter") or {}).get("n_weak_dropped"),
            }
            for r in updated[:6]
        ],
    }


def latest_research(cfg: dict[str, Any]) -> dict[str, Any] | None:
    rurl = redis_url_from_env(cfg)
    try:
        cached = cache_get(rurl, "ashare:research:latest") or cache_get(rurl, "ashare:picks:latest")
        if cached:
            return dict(cached)
    except Exception:  # noqa: BLE001
        pass
    path = _reports_dir(cfg) / "latest.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return None
