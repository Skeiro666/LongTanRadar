from __future__ import annotations

import json
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

    app = FastAPI(title="龙探雷达 API", version="0.2.0", lifespan=lifespan)
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

    @app.post("/api/research/run")
    def api_research_run(body: PicksBody = PicksBody()) -> dict[str, Any]:
        from ashare.services.research import run_research

        try:
            return run_research(get_cfg(), top_n=body.top_n)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=str(exc)) from exc

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

        cfg = get_cfg()
        tracker = get_cost_tracker(cfg)
        out = tracker.summary()
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
