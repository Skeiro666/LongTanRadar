from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Optional

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from ashare.ai.review import review_backtest
from ashare.backtest.engine import BacktestEngine, broker_from_cfg
from ashare.config import load_config
from ashare.data.provider import ensure_panel
from ashare.ml.registry import list_models
from ashare.ml.train import train_model
from ashare.strategy import build_risk, build_strategy

_CFG_PATH: str | None = None


def get_cfg() -> dict[str, Any]:
    return load_config(_CFG_PATH or "config/default.yaml")


class TrainBody(BaseModel):
    num_leaves: Optional[int] = None
    learning_rate: Optional[float] = None
    min_data_in_leaf: Optional[int] = None
    label_horizon: Optional[int] = None
    n_estimators: Optional[int] = None


class BacktestBody(BaseModel):
    strategy: str = "ml_lgbm"
    run_id: Optional[str] = None
    start: Optional[str] = None
    end: Optional[str] = None


class PicksBody(BaseModel):
    top_n: Optional[int] = None


class TradePicksBody(BaseModel):
    regenerate: bool = False
    confirm_live: bool = False


class ManualOrderBody(BaseModel):
    symbol: str
    side: str
    quantity: int
    price: Optional[float] = None


class AgentStartBody(BaseModel):
    interval_sec: Optional[int] = None
    run_now: bool = True


def create_app(config_path: str | None = None) -> FastAPI:
    global _CFG_PATH
    _CFG_PATH = config_path

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        cfg = get_cfg()
        from ashare.services.agent import restore_state, start_agent

        restore_state(cfg)
        if bool(cfg.get("agent", {}).get("autostart", False)):
            start_agent(interval_sec=float(cfg.get("agent", {}).get("interval_sec") or 3600), run_now=True)
        yield
        from ashare.services.agent import stop_agent

        stop_agent()

    app = FastAPI(title="寻龙尺 API", version="0.2.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        cfg = get_cfg()
        from ashare.db import database_url_from_env, ping_db, ping_redis, redis_url_from_env
        from ashare.services.trading import broker_mode

        return {
            "status": "ok",
            "postgres": ping_db(database_url_from_env(cfg)),
            "redis": ping_redis(redis_url_from_env(cfg)),
            "broker_mode": broker_mode(cfg),
        }

    @app.get("/api/config")
    def api_config() -> dict[str, Any]:
        cfg = get_cfg()
        from ashare.services.trading import broker_mode

        return {
            "product": cfg.get("product") or {},
            "strategy": cfg.get("strategy", {}),
            "ml": {k: v for k, v in cfg.get("ml", {}).items() if k != "api_key"},
            "risk": cfg.get("risk", {}),
            "backtest": cfg.get("backtest", {}),
            "trading": cfg.get("trading", {}),
            "broker": {
                "mode": broker_mode(cfg),
                "live_ready": bool(
                    cfg.get("_env", {}).get("I_UNDERSTAND_LIVE") == "1"
                    and (cfg.get("_env", {}).get("QMT_ACCOUNT_ID") or "")
                ),
            },
            "ai": {
                "enabled": cfg.get("ai", {}).get("enabled"),
                "model": cfg.get("ai", {}).get("model"),
                "base_url": cfg.get("ai", {}).get("base_url"),
                "has_key": bool(cfg.get("_env", {}).get("AI_API_KEY")),
                "roundtable": cfg.get("ai", {}).get("roundtable"),
                "committee": {
                    "mode": ((cfg.get("ai") or {}).get("committee") or {}).get("mode"),
                    "roles": [
                        {
                            "id": r.get("id"),
                            "name": r.get("name"),
                            "model": r.get("model"),
                            "base_url": r.get("base_url") or cfg.get("ai", {}).get("base_url"),
                        }
                        for r in (((cfg.get("ai") or {}).get("committee") or {}).get("roles") or [])
                    ],
                },
            },
        }

    @app.post("/api/train")
    def api_train(body: TrainBody) -> dict[str, Any]:
        cfg = get_cfg()
        overrides: dict[str, Any] = {}
        if body.num_leaves is not None:
            overrides["num_leaves"] = body.num_leaves
        if body.learning_rate is not None:
            overrides["learning_rate"] = body.learning_rate
        if body.min_data_in_leaf is not None:
            overrides["min_data_in_leaf"] = body.min_data_in_leaf
        if body.label_horizon is not None:
            overrides["label_horizon"] = body.label_horizon
        if body.n_estimators is not None:
            overrides["n_estimators"] = body.n_estimators
        # Force sample if no cache — ensure_panel handles it
        try:
            return train_model(cfg, overrides=overrides or None)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/models")
    def api_models() -> list[dict[str, Any]]:
        return list_models(get_cfg())

    @app.post("/api/backtest")
    def api_backtest(body: BacktestBody) -> dict[str, Any]:
        cfg = get_cfg()
        import copy

        cfg = copy.deepcopy(cfg)
        cfg.setdefault("strategy", {})["name"] = body.strategy
        if body.run_id:
            cfg.setdefault("ml", {})["run_id"] = body.run_id
        bt = cfg.setdefault("backtest", {})
        if body.start:
            bt["start"] = body.start
        if body.end:
            bt["end"] = body.end

        panel = ensure_panel(cfg)
        if not panel:
            raise HTTPException(status_code=400, detail="No market data")
        root = Path(cfg["_root"])
        broker = broker_from_cfg(
            cfg,
            persist=False,
            reset=True,
            state_file=str(root / "data" / "_api_backtest_state.json"),
        )
        engine = BacktestEngine(
            strategy=build_strategy(cfg),
            risk=build_risk(cfg),
            broker=broker,
            execute_at=str(cfg.get("trading", {}).get("execute_at", "open")),
            lot_size=int(cfg.get("trading", {}).get("lot_size", 100)),
        )
        result = engine.run(panel, start=str(bt.get("start")), end=str(bt.get("end")))
        payload = {
            "initial_balance": result.initial_balance,
            "final_equity": result.final_equity,
            "total_return": result.total_return,
            "annualized": result.annualized,
            "max_drawdown": result.max_drawdown,
            "sharpe": result.sharpe,
            "turnover": result.turnover,
            "win_rate": result.win_rate,
            "trades": result.trades,
            "yearly": result.yearly,
            "equity_curve": result.equity_curve,
            "trade_log": result.trade_log[-50:],
            "strategy": body.strategy,
        }
        out = root / "data" / "backtest_result.json"
        out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return payload

    @app.get("/api/paper")
    def api_paper() -> dict[str, Any]:
        cfg = get_cfg()
        state_file = Path(cfg.get("paper", {}).get("state_file", "data/paper_state.json"))
        if not state_file.exists():
            return {"state": None, "message": "No paper state yet"}
        return json.loads(state_file.read_text(encoding="utf-8"))

    @app.get("/api/backtest/latest")
    def api_backtest_latest() -> dict[str, Any]:
        cfg = get_cfg()
        path = Path(cfg["_root"]) / "data" / "backtest_result.json"
        if not path.exists():
            raise HTTPException(status_code=404, detail="No backtest result")
        return json.loads(path.read_text(encoding="utf-8"))

    @app.post("/api/review")
    def api_review() -> dict[str, Any]:
        cfg = get_cfg()
        path = Path(cfg["_root"]) / "data" / "backtest_result.json"
        if not path.exists():
            raise HTTPException(status_code=404, detail="No backtest result")
        metrics = json.loads(path.read_text(encoding="utf-8"))
        note = review_backtest(cfg, metrics)
        if not note:
            return {
                "text": None,
                "message": "AI review skipped. Set AI_API_KEY in .env",
            }
        return {"text": note}

    @app.get("/api/picks/latest")
    def api_picks_latest() -> dict[str, Any]:
        from ashare.services.picks import latest_picks

        data = latest_picks(get_cfg())
        if not data:
            raise HTTPException(status_code=404, detail="No picks yet — POST /api/picks/run")
        return data

    @app.post("/api/picks/run")
    def api_picks_run(body: PicksBody = PicksBody()) -> dict[str, Any]:
        from ashare.services.picks import run_picks

        try:
            return run_picks(get_cfg(), top_n=body.top_n)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/research/latest")
    def api_research_latest() -> dict[str, Any]:
        from ashare.services.research import latest_research

        data = latest_research(get_cfg())
        if not data:
            raise HTTPException(status_code=404, detail="No research yet — POST /api/research/run")
        return data

    @app.get("/api/research/progress")
    def api_research_progress() -> dict[str, Any]:
        from ashare.research.progress import get_research_progress

        snap = get_research_progress().snapshot()
        if snap.get("status") == "done" and get_research_progress().result:
            snap["result"] = get_research_progress().result
        return snap

    @app.post("/api/research/run")
    def api_research_run(body: PicksBody = PicksBody(), sync: bool = False) -> dict[str, Any]:
        from ashare.research.progress import get_research_progress
        from ashare.services.research import run_research

        progress = get_research_progress()
        if progress.running:
            raise HTTPException(status_code=409, detail="Research already running — poll /api/research/progress")

        cfg = get_cfg()

        try:
            run_id = progress.begin()
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

        def _wrapped() -> None:
            try:
                result = run_research(cfg, top_n=body.top_n)
                progress.finish(result)
            except Exception as exc:  # noqa: BLE001
                progress.fail(str(exc))

        threading.Thread(target=_wrapped, daemon=True).start()
        return {"status": "running", "run_id": run_id, "poll": "/api/research/progress"}

    @app.post("/api/research/refresh-news")
    def api_research_refresh_news() -> dict[str, Any]:
        """Refresh platform report news only (no LLM). Use after news filter upgrades."""
        from ashare.services.research import refresh_report_news

        try:
            return refresh_report_news(get_cfg())
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/ai/cost")
    def api_ai_cost() -> dict[str, Any]:
        from ashare.ai.cost_tracker import get_cost_tracker
        from ashare.services.research import latest_research

        cfg = get_cfg()
        tracker = get_cost_tracker(cfg)
        research = latest_research(cfg) or {}
        uni = research.get("candidate_union") or {}
        canonical = list(research.get("canonical_decisions") or [])
        n_buys = sum(1 for d in canonical if d.get("committee_approve"))
        context = {
            "n_candidates": uni.get("n_union") or len(uni.get("universe") or []),
            "n_research": len(research.get("platform_reports") or []),
            "n_council": len([r for r in (uni.get("universe") or []) if r.get("in_council")]),
            "n_buys": n_buys,
        }
        out = tracker.summary(context=context)
        out["recent"] = tracker.load_recent(limit=30)
        return out

    @app.get("/api/factors")
    def api_factors() -> dict[str, Any]:
        from ashare.factors import FactorEngine, list_factors
        from ashare.factors.score import factor_weights

        cfg = get_cfg()
        eng = FactorEngine(cfg)
        return {
            "factors": list_factors(),
            "weights": factor_weights(cfg),
            "catalog_version": eng.catalog.version,
            "available": eng.catalog.available_names(),
            "value_available": eng.value_available,
            "quality_available": eng.quality_available,
            "leader_weights": eng.catalog.leader_weights,
        }

    @app.get("/api/news/discovery")
    def api_news_discovery() -> dict[str, Any]:
        from ashare.news.opportunity import NewsOpportunityEngine

        data = NewsOpportunityEngine(get_cfg()).load_latest()
        if not data:
            raise HTTPException(status_code=404, detail="No news discovery yet — POST /api/research/run")
        return data

    @app.get("/api/news/{symbol}")
    def api_news_symbol(symbol: str, name: str = "") -> dict[str, Any]:
        from ashare.news.engine import NewsIntelligenceEngine

        try:
            return NewsIntelligenceEngine(get_cfg()).collect_stock(symbol, name=name, persist=True)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/research/candidates")
    def api_research_candidates(candidate_source: str = "") -> dict[str, Any]:
        from ashare.services.research import latest_research

        data = latest_research(get_cfg()) or {}
        uni = data.get("candidate_union") or {}
        rows = list(uni.get("universe") or [])
        if candidate_source:
            rows = [r for r in rows if candidate_source in (r.get("candidate_sources") or [])]
        return {
            "n": len(rows),
            "candidates": rows,
            "rejected": uni.get("rejected") or [],
            "as_of": data.get("as_of"),
        }

    @app.get("/api/research/hypotheses")
    def api_research_hypotheses(symbol: str = "") -> dict[str, Any]:
        from ashare.services.research import latest_research
        from ashare.symbols import to_symbol

        data = latest_research(get_cfg()) or {}
        rows: list[dict[str, Any]] = []
        for r in (data.get("candidate_union") or {}).get("universe") or []:
            for h in r.get("research_hypotheses") or []:
                if symbol and to_symbol(r.get("symbol")) != to_symbol(symbol):
                    continue
                rows.append({**h, "symbol": r.get("symbol")})
        for c in (data.get("news_discovery") or {}).get("news_candidates") or []:
            if symbol and to_symbol(c.get("symbol")) != to_symbol(symbol):
                continue
            for h in c.get("research_hypotheses") or []:
                rows.append({**h, "symbol": c.get("symbol")})
        return {"n": len(rows), "hypotheses": rows, "as_of": data.get("as_of")}

    @app.get("/api/research/outcomes")
    def api_research_outcomes(horizon: str = "5") -> dict[str, Any]:
        from ashare.research.tracking import ReviewEngine
        from ashare.services.research import latest_research

        cfg = get_cfg()
        data = latest_research(cfg) or {}
        pack = data.get("research_outcomes") or {}
        if pack.get("available"):
            return {
                "available": True,
                "as_of": data.get("as_of"),
                "horizon": pack.get("horizon") or horizon,
                "n": pack.get("n") or len(pack.get("outcomes") or []),
                "outcomes": pack.get("outcomes") or [],
                "by_rating": pack.get("by_rating"),
            }
        eng = ReviewEngine(cfg)
        outcomes = eng.load_outcomes()
        if not outcomes:
            return {"available": False, "n": 0, "outcomes": [], "note": "no_outcomes_yet"}
        return {
            "available": True,
            "horizon": horizon,
            "n": len(outcomes),
            "outcomes": outcomes,
            "by_rating": eng.summarize_by_rating(outcomes, horizon=horizon),
        }

    @app.get("/api/research/attribution")
    def api_research_attribution(horizon: str = "5") -> dict[str, Any]:
        from ashare.research.tracking import ReviewEngine
        from ashare.services.research import latest_research

        cfg = get_cfg()
        data = latest_research(cfg) or {}
        pack = data.get("research_outcomes") or {}
        if pack.get("attribution"):
            return {
                "available": True,
                "as_of": data.get("as_of"),
                "horizon": pack.get("horizon") or horizon,
                "attribution": pack.get("attribution"),
                "by_rating": pack.get("by_rating"),
                "ai_incremental_alpha": pack.get("ai_incremental_alpha"),
                "ai_topk_ablation": pack.get("ai_topk_ablation"),
                "ai_incremental_alpha_legacy": pack.get("ai_incremental_alpha_legacy"),
                "role_ablation": pack.get("role_ablation"),
                "model_benchmark": pack.get("model_benchmark"),
                "discovery_attribution": pack.get("discovery_attribution"),
                "benchmark": pack.get("benchmark"),
            }
        eng = ReviewEngine(cfg)
        outcomes = eng.load_outcomes()
        if not outcomes:
            return {"available": False, "attribution": {}, "note": "no_outcomes_yet"}
        return {
            "available": True,
            "horizon": horizon,
            "attribution": eng.summarize_by_source(outcomes, horizon=horizon),
            "by_rating": eng.summarize_by_rating(outcomes, horizon=horizon),
        }

    @app.get("/api/research/alpha-dashboard")
    def api_research_alpha_dashboard(horizon: str = "5") -> dict[str, Any]:
        from ashare.ai.cost_tracker import get_cost_tracker
        from ashare.services.research import latest_research

        cfg = get_cfg()
        research = latest_research(cfg) or {}
        pack = research.get("research_outcomes") or {}
        uni = research.get("candidate_union") or {}
        canonical = list(research.get("canonical_decisions") or [])
        n_buys = sum(1 for d in canonical if d.get("committee_approve"))
        tracker = get_cost_tracker(cfg)
        cost = tracker.summary(
            context={
                "n_candidates": uni.get("n_union") or len(uni.get("universe") or []),
                "n_research": len(research.get("platform_reports") or []),
                "n_council": len([r for r in (uni.get("universe") or []) if r.get("in_council")]),
                "n_buys": n_buys,
            }
        )
        eff = cost.get("efficiency") or {}
        cycle = cost.get("cycle_cost") or cost.get("cycle") or {}
        topk = pack.get("ai_topk_ablation") or pack.get("ai_incremental_alpha") or {}
        incr = topk.get("ai_incremental_alpha")
        legacy = pack.get("ai_incremental_alpha_legacy") or {}
        total_tokens = int(cycle.get("total_tokens") or 0)
        alpha_per_100k = None
        if incr is not None and total_tokens > 0:
            alpha_per_100k = float(incr) / (total_tokens / 100_000.0)
        return {
            "available": bool(research),
            "as_of": research.get("as_of"),
            "horizon": pack.get("horizon") or horizon,
            "cost": {
                "cycle": cycle,
                "daily": cost.get("daily_cost") or cost.get("daily"),
                "efficiency": eff,
                "alpha_per_100k_tokens": alpha_per_100k,
            },
            "discovery_attribution": pack.get("discovery_attribution"),
            "ai_incremental_alpha": topk,
            "ai_topk_ablation": topk,
            "ai_incremental_alpha_legacy": legacy,
            "role_ablation": pack.get("role_ablation"),
            "model_benchmark": pack.get("model_benchmark"),
            "attribution": pack.get("attribution"),
            "benchmark": pack.get("benchmark"),
            "benchmark_snapshot": pack.get("benchmark_snapshot"),
            "decision_chain": research.get("decision_chain"),
            "decision_consistency": research.get("decision_consistency"),
            "gate": uni.get("gate"),
            "n_candidates": uni.get("n_union"),
            "n_research": len(research.get("platform_reports") or []),
            "n_buys": n_buys,
        }

    @app.get("/api/research/role-ablation")
    def api_research_role_ablation(horizon: str = "5") -> dict[str, Any]:
        from ashare.services.research import latest_research

        data = latest_research(get_cfg()) or {}
        pack = data.get("research_outcomes") or {}
        ab = pack.get("role_ablation")
        if ab:
            return {"available": True, "as_of": data.get("as_of"), "role_ablation": ab}
        return {"available": False, "note": "run_research first"}

    @app.get("/api/research/model-benchmark")
    def api_research_model_benchmark() -> dict[str, Any]:
        from ashare.ai.cost_tracker import get_cost_tracker
        from ashare.research.model_benchmark import build_model_benchmark
        from ashare.services.research import latest_research

        cfg = get_cfg()
        data = latest_research(cfg) or {}
        pack = data.get("research_outcomes") or {}
        mb = pack.get("model_benchmark")
        if mb:
            return {"available": True, "as_of": data.get("as_of"), "model_benchmark": mb}
        cycle = get_cost_tracker(cfg).summary().get("cycle_cost") or {}
        return {
            "available": bool(cycle.get("by_model")),
            "model_benchmark": build_model_benchmark(cfg, cycle_summary=cycle, ai_incremental_alpha=pack.get("ai_incremental_alpha")),
        }

    @app.get("/api/optimizer/experiments")
    def api_optimizer_experiments(limit: int = 20) -> dict[str, Any]:
        from ashare.ai.optimizer_experiment import list_experiments

        rows = list_experiments(get_cfg(), limit=limit)
        return {"n": len(rows), "experiments": rows}

    @app.get("/api/research/sessions")
    def api_research_sessions(limit: int = 50) -> dict[str, Any]:
        from pathlib import Path

        root = Path(get_cfg().get("_root", "."))
        idx = root / "data" / "research_sessions.jsonl"
        rows: list[dict[str, Any]] = []
        if idx.exists():
            for line in idx.read_text(encoding="utf-8").splitlines()[-limit:]:
                try:
                    import json

                    rows.append(json.loads(line))
                except Exception:  # noqa: BLE001
                    continue
        return {"sessions": list(reversed(rows))}

    @app.get("/api/research/session/{research_id}")
    def api_research_session(research_id: str) -> dict[str, Any]:
        from pathlib import Path
        import json

        root = Path(get_cfg().get("_root", "."))
        path = root / "data" / "research_snapshots" / f"{research_id}.json"
        if not path.exists():
            raise HTTPException(status_code=404, detail="snapshot not found")
        return json.loads(path.read_text(encoding="utf-8"))

    @app.get("/api/research/terminal")
    def api_research_terminal() -> dict[str, Any]:
        from ashare.services.research_terminal import build_research_terminal

        return build_research_terminal(get_cfg())

    @app.get("/api/research/detail/{research_id}/{symbol}")
    def api_research_detail(research_id: str, symbol: str) -> dict[str, Any]:
        from ashare.services.research_terminal import build_research_detail

        return build_research_detail(get_cfg(), research_id, symbol)

    @app.get("/api/notifications/history")
    def api_notifications_history(limit: int = 100) -> dict[str, Any]:
        from ashare.services.notification_history import build_notification_history

        return build_notification_history(get_cfg(), limit=limit)

    @app.get("/api/token-dashboard")
    def api_token_dashboard() -> dict[str, Any]:
        from ashare.services.token_dashboard import build_token_dashboard

        return build_token_dashboard(get_cfg())

    @app.get("/api/notifications")
    def api_notifications(limit: int = 100) -> dict[str, Any]:
        from ashare.notification.store import NotificationStore

        rows = NotificationStore(get_cfg()).list_recent(limit=limit)
        return {"n": len(rows), "notifications": rows}

    @app.get("/api/notifications/stats")
    def api_notifications_stats() -> dict[str, Any]:
        from datetime import datetime, timedelta, timezone

        from ashare.notification.outcome import refresh_notification_outcomes
        from ashare.notification.production import production_summary
        from ashare.notification.store import NotificationStore

        cfg = get_cfg()
        store = NotificationStore(cfg)
        rows = store.list_recent(500)
        now = datetime.now(timezone.utc)

        def _in_days(n: int) -> list[dict[str, Any]]:
            cutoff = now - timedelta(days=n)
            out = []
            for r in rows:
                ts = r.get("sent_at") or r.get("created_at")
                if not ts:
                    continue
                try:
                    dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                    if dt >= cutoff:
                        out.append(r)
                except ValueError:
                    continue
            return out

        today = _in_days(1)
        w7 = _in_days(7)
        m30 = _in_days(30)
        sent = [r for r in rows if r.get("status") == "SENT"]
        failed = [r for r in rows if r.get("status") == "FAILED"]
        cooldown = sum(1 for r in rows if r.get("status") == "COOLDOWN")
        duplicate = sum(1 for r in rows if r.get("status") == "DUPLICATE")

        try:
            outcome_pack = refresh_notification_outcomes(cfg)
        except Exception:  # noqa: BLE001
            outcome_pack = {"available": False}

        return {
            "today_count": len(today),
            "days_7_count": len(w7),
            "days_30_count": len(m30),
            "success_rate": len(sent) / max(len(sent) + len(failed), 1),
            "BUY_count": sum(1 for r in sent if r.get("level") == "BUY"),
            "STRONG_BUY_count": sum(1 for r in sent if r.get("level") == "STRONG_BUY"),
            "RISK_EXIT_count": sum(1 for r in sent if r.get("level") == "RISK_EXIT"),
            "RATING_EXIT_count": sum(1 for r in sent if r.get("level") == "RATING_EXIT"),
            "cooldown_count": cooldown,
            "duplicate_count": duplicate,
            "notification_attribution": outcome_pack.get("notification_attribution"),
            "discovery_attribution": outcome_pack.get("discovery_attribution"),
            "notification_llm_cost": 0,
            "production": production_summary(cfg),
        }

    @app.get("/api/notifications/status")
    def api_notification_status(symbol: str = "", research_id: str = "") -> dict[str, Any]:
        from ashare.notification.service import notification_status_for_symbol

        if not symbol:
            raise HTTPException(status_code=400, detail="symbol required")
        return notification_status_for_symbol(get_cfg(), symbol, research_id or None)

    @app.get("/api/leader/monitor")
    def api_leader_monitor() -> dict[str, Any]:
        from ashare.services.leader_monitor import build_leader_monitor

        return build_leader_monitor(get_cfg())

    @app.get("/api/leader/dashboard")
    def api_leader_dashboard() -> dict[str, Any]:
        from ashare.services.leader_monitor import build_leader_monitor

        pack = build_leader_monitor(get_cfg())
        return {
            "as_of": pack.get("as_of"),
            "stage_performance": pack.get("stage_performance") or {},
            "board_performance": pack.get("board_performance") or {},
            "focus_stats": pack.get("focus_stats") or {},
            "buy_ready_count": pack.get("buy_ready_count"),
            "has_buy_ready": pack.get("has_buy_ready"),
        }

    @app.get("/api/alpha-lab")
    def api_alpha_lab(window: str = "all") -> dict[str, Any]:
        from ashare.services.alpha_lab import build_alpha_lab

        return build_alpha_lab(get_cfg(), window=window)

    @app.get("/api/exit/book")
    def api_exit_book() -> dict[str, Any]:
        from ashare.services.exit_lab import evaluate_exit_book

        return evaluate_exit_book(get_cfg())

    @app.get("/api/exit/lab")
    def api_exit_lab() -> dict[str, Any]:
        from ashare.services.exit_lab import build_exit_lab

        return build_exit_lab(get_cfg())

    @app.get("/api/exit/{symbol}")
    def api_exit_symbol(symbol: str) -> dict[str, Any]:
        from ashare.services.exit_lab import evaluate_exit_book

        pack = evaluate_exit_book(get_cfg())
        for row in pack.get("positions") or []:
            if str(row.get("symbol")) == symbol or str(row.get("symbol")).endswith(symbol):
                return {
                    **row,
                    "chart": (pack.get("charts") or {}).get(row.get("symbol")),
                }
        raise HTTPException(status_code=404, detail="position or exit signal not found")

    @app.post("/api/ml/rank/train")
    def api_ml_rank_train() -> dict[str, Any]:
        from ashare.data.provider import ensure_panel
        from ashare.ml.ranking import MLRankingEngine

        cfg = get_cfg()
        try:
            panel = ensure_panel(cfg)
            return MLRankingEngine(cfg).train(panel)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/ml/weight-experiments")
    def api_ml_weight_experiments(limit: int = 20) -> dict[str, Any]:
        from ashare.ml.weight_experiment import list_weight_experiments

        rows = list_weight_experiments(get_cfg(), limit=limit)
        return {"n": len(rows), "experiments": rows}

    @app.post("/api/ml/weight-experiment")
    def api_ml_weight_experiment() -> dict[str, Any]:
        from ashare.data.provider import ensure_panel
        from ashare.ml.weight_experiment import run_ml_weight_experiment

        cfg = get_cfg()
        try:
            panel = ensure_panel(cfg)
            return run_ml_weight_experiment(panel, cfg, persist=True)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/account")
    def api_account() -> dict[str, Any]:
        from ashare.data.provider import latest_marks
        from ashare.services.trading import PaperTradingBroker, build_live_or_paper, snapshot_account

        cfg = get_cfg()
        try:
            broker = build_live_or_paper(cfg)
            broker.connect()
            if isinstance(broker, PaperTradingBroker):
                broker.set_marks(latest_marks(cfg))
            return snapshot_account(cfg, broker)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/orders")
    def api_orders() -> list[dict[str, Any]]:
        from ashare.services.trading import list_orders

        return list_orders(get_cfg())

    @app.post("/api/trade/picks")
    def api_trade_picks(body: TradePicksBody = TradePicksBody()) -> dict[str, Any]:
        from ashare.services.trading import execute_picks

        try:
            return execute_picks(
                get_cfg(),
                regenerate=body.regenerate,
                force_live=body.confirm_live,
            )
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/trade/auto")
    def api_trade_auto() -> dict[str, Any]:
        """Paper-only: reset account → pick → buy."""
        from ashare.services.trading import run_auto_paper

        try:
            return run_auto_paper(get_cfg(), reset=True)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/trade/order")
    def api_trade_order(body: ManualOrderBody) -> dict[str, Any]:
        from ashare.services.trading import place_manual_order

        try:
            return place_manual_order(
                get_cfg(),
                symbol=body.symbol,
                side=body.side,
                quantity=body.quantity,
                price=body.price,
            )
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/pnl")
    def api_pnl() -> dict[str, Any]:
        from ashare.data.names import attach_names
        from ashare.data.provider import latest_marks
        from ashare.services.pnl import pnl_summary, record_equity
        from ashare.services.trading import PaperTradingBroker, build_live_or_paper

        cfg = get_cfg()
        try:
            broker = build_live_or_paper(cfg)
            broker.connect()
            held = [p.symbol for p in broker.get_positions()]
            if isinstance(broker, PaperTradingBroker) and held:
                try:
                    broker.set_marks(latest_marks(cfg, held))
                except Exception:  # noqa: BLE001
                    pass
            acc = broker.get_account()
            positions = [
                {
                    "symbol": p.symbol,
                    "shares": p.shares,
                    "available": p.available,
                    "cost_price": p.cost_price,
                }
                for p in broker.get_positions()
            ]
            positions = attach_names(positions, cfg)
            record_equity(cfg, equity=float(acc.equity), cash=float(acc.cash), source="api")
            out = pnl_summary(cfg)
            out["positions"] = positions
            out["cash"] = acc.cash
            return out
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/agent")
    def api_agent_status() -> dict[str, Any]:
        from ashare.services.agent import snapshot
        from ashare.services.pnl import pnl_summary

        cfg = get_cfg()
        st = snapshot()
        st["broker_mode"] = "paper"
        st["autostart"] = bool(cfg.get("agent", {}).get("autostart", False))
        st["interval_sec"] = st.get("interval_sec") or cfg.get("agent", {}).get("interval_sec")
        st["ai_model"] = cfg.get("ai", {}).get("model")
        st["picks_style"] = "leader"
        st["universe_mode"] = cfg.get("universe", {}).get("mode")
        try:
            st["pnl"] = {
                k: pnl_summary(cfg).get(k)
                for k in ("equity", "pnl_day", "pnl_total", "return_total", "initial_balance")
            }
        except Exception:  # noqa: BLE001
            st["pnl"] = None
        return st

    @app.post("/api/agent/start")
    def api_agent_start(body: AgentStartBody = AgentStartBody()) -> dict[str, Any]:
        from ashare.services.agent import start_agent

        try:
            return start_agent(interval_sec=body.interval_sec, run_now=body.run_now)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/agent/stop")
    def api_agent_stop() -> dict[str, Any]:
        from ashare.services.agent import stop_agent

        return stop_agent()

    @app.post("/api/agent/reset")
    def api_agent_reset() -> dict[str, Any]:
        """清空模拟账户 + 盈亏曲线，本金回到 3000，并重新开一轮。"""
        from ashare.services.agent import reset_and_restart

        try:
            return reset_and_restart()
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/agent/cycle")
    def api_agent_cycle() -> dict[str, Any]:
        from ashare.services.agent import run_cycle

        try:
            return run_cycle(get_cfg(), reset_paper=False)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return app


app = create_app()
