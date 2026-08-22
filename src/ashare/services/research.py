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
    from ashare.ai.roundtable import run_roundtable
    from ashare.candidate import CandidateEngine
    from ashare.config_loaders import load_yaml_config
    from ashare.portfolio import PortfolioEngine, RiskFilterEngine, market_regime
    from ashare.research.session import ResearchSessionEngine

    pool = build_leader_pool(cfg)
    cfg["_last_screen"] = pool
    symbols = [to_symbol(s) for s in (pool.get("symbols") or [])]
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

    panel = ensure_panel(cfg, symbols)
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

        news_discovery = NewsOpportunityEngine(cfg).discover(as_of=as_of_dt, persist=True)
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
    if bool(rt_cfg.get("roundtable", True)) and shortlist:
        roundtable = run_roundtable(cfg, shortlist)
        picks = list(roundtable.get("reviews") or shortlist)
    else:
        roundtable = {"source": "disabled", "summary": "圆桌关闭，仅因子排序", "roles": [], "debate": []}
        picks = []
        for i, row in enumerate(shortlist):
            picks.append(
                {
                    **row,
                    "committee_verdict": "watch",
                    "committee_approve": False,
                    "ai_approve": False,
                    "weight": 0.0,
                }
            )

    # --- Platform v2 path (Candidate → ML rank hint → Council sessions) ---
    platform_reports: list[dict[str, Any]] = []
    uni: dict[str, Any] = {}
    outcome_pack: dict[str, Any] = {"available": False, "note": "no_platform_reports"}
    research_yaml = load_yaml_config(cfg, "research")
    use_platform = bool(research_yaml.get("enabled", True))
    if use_platform:
        try:
            cand_eng = CandidateEngine(cfg)
            uni = cand_eng.build_research_universe(panel=panel, pool=pool, news_discovery=news_discovery)
            regime = market_regime(
                panel_mom20=[
                    float((r.get("factors") or {}).get("momentum_20d") or 0)
                    for r in uni.get("research_universe") or []
                ]
            )
            for r in uni.get("research_universe") or []:
                r["market_regime"] = regime
            session = ResearchSessionEngine(cfg)
            platform_reports = session.run_pool(uni.get("research_universe") or [], panel=panel)
            # map BUY ratings to watch by default for trading (rating ≠ action)
            risk = RiskFilterEngine(cfg)
            port = PortfolioEngine(cfg)
            mapped = []
            src_map = {to_symbol(r["symbol"]): r.get("candidate_sources") for r in (uni.get("research_universe") or [])}
            for rep in platform_reports:
                action = (rep.get("decision") or {}).get("action") or "WATCH"
                rating = (rep.get("decision") or {}).get("research_rating") or "WATCH"
                sym = to_symbol(rep["symbol"])
                # keep sources on report for attribution
                if not rep.get("candidate_sources"):
                    rep["candidate_sources"] = src_map.get(sym) or []
                bar = snap["bars"].get(sym)
                allow, reason = (True, "ok")
                if bar is not None:
                    allow, reason = risk.allow_open(
                        {
                            "is_st": bar.is_st,
                            "is_halt": bar.is_halt,
                            "limit_up": bar.limit_up,
                            "amount": bar.amount,
                        }
                    )
                # Trading only if chairman says SMALL_POSITION and risk ok — still not auto-buy from rating alone
                approve = allow and action == "SMALL_POSITION" and rating in {"BUY", "STRONG_BUY"}
                mapped.append(
                    {
                        "symbol": sym,
                        "name": rep.get("name"),
                        "committee_verdict": "buy" if approve else ("watch" if rating in {"BUY", "WATCH", "STRONG_BUY"} else "pass"),
                        "committee_approve": approve,
                        "ai_approve": approve,
                        "ai_confidence": (rep.get("chairman") or {}).get("confidence"),
                        "committee_thesis": (rep.get("chairman") or {}).get("base_case"),
                        "committee_risks": ",".join((rep.get("chairman") or {}).get("risks") or []),
                        "committee_horizon": (rep.get("chairman") or {}).get("time_horizon"),
                        "research_rating": rating,
                        "trading_action": action,
                        "research_id": rep.get("research_id"),
                        "reason": "platform_council",
                        "candidate_sources": src_map.get(sym) or [],
                        "weight": 0.0,
                    }
                )
            # Prefer platform picks when available; keep legacy roundtable in payload
            if mapped:
                picks = mapped
                weighted = port.suggest_weights(
                    [{**p, "leader_score": 0.5 if p.get("committee_verdict") == "buy" else 0.0} for p in picks]
                )
                wmap = {w["symbol"]: w.get("target_weight", 0) for w in weighted}
                for p in picks:
                    p["weight"] = float(wmap.get(p["symbol"]) or 0.0) if p.get("committee_approve") else 0.0
            # Phase 7: outcome attribution by discovery source (descriptive only)
            try:
                from ashare.research.tracking import ReviewEngine

                horizon = str(((research_yaml.get("tracking") or {}).get("attribution_horizon") or 5))
                outcome_pack = ReviewEngine(cfg).attribution_report(
                    platform_reports, panel, horizon=horizon, persist=True
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("outcome attribution skipped: %s", exc)
                outcome_pack = {"available": False, "error": str(exc)[:300]}
        except Exception as exc:  # noqa: BLE001
            logger.warning("platform research path failed, legacy roundtable kept: %s", exc)

    approved = [p for p in picks if p.get("committee_approve") or p.get("committee_verdict") == "buy"]
    if not any(p.get("weight") for p in picks):
        w = 1.0 / len(approved) if approved else 0.0
        for p in picks:
            p["weight"] = w if (p.get("committee_approve") or p.get("committee_verdict") == "buy") else 0.0
            p.setdefault("reason", "leader_factor_roundtable")

    picks = attach_names(picks, cfg)
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
                    "trigger": r.get("trigger"),
                    "research_hypotheses": r.get("research_hypotheses") or [],
                }
                for r in (uni.get("research_universe") or [])
            ],
            "rejected": (uni.get("rejected") or [])[:80],
        },
        "platform_reports": [
            {
                "research_id": r.get("research_id"),
                "symbol": r.get("symbol"),
                "name": r.get("name"),
                "rating": (r.get("decision") or {}).get("research_rating"),
                "action": (r.get("decision") or {}).get("action"),
                "candidate_sources": r.get("candidate_sources") or [],
                "research_hypotheses": r.get("research_hypotheses") or [],
                "chairman": {
                    "confidence": (r.get("chairman") or {}).get("confidence"),
                    "base_case": (r.get("chairman") or {}).get("base_case"),
                    "risks": (r.get("chairman") or {}).get("risks"),
                },
                "news": {
                    "counts": (r.get("news_package") or {}).get("counts"),
                    "net_event_score": (r.get("news_package") or {}).get("net_event_score"),
                    "incomplete": (r.get("news_package") or {}).get("news_data_incomplete"),
                    "last_7d": (r.get("news_package") or {}).get("last_7d") or [],
                    "timeline": (r.get("news_package") or {}).get("timeline") or [],
                    "conflicts": (r.get("news_package") or {}).get("conflicts") or [],
                    "expectation": (r.get("news_package") or {}).get("expectation"),
                },
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
            "note": outcome_pack.get("note") or outcome_pack.get("error"),
        },
        "roundtable": {
            "summary": roundtable.get("summary"),
            "source": roundtable.get("source"),
            "replay_notes": roundtable.get("replay_notes"),
            "models_used": roundtable.get("models_used") or [],
            "chair_model": roundtable.get("chair_model"),
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
                }
                for r in (roundtable.get("reviews") or picks)
            ],
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    persist_report(cfg, payload)
    _persist_picks_compat(cfg, payload)
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
