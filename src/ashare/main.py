from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from ashare.ai.review import review_backtest
from ashare.backtest.engine import BacktestEngine, broker_from_cfg
from ashare.config import load_config
from ashare.data.provider import cache_universe, ensure_panel
from ashare.monitor.logger import setup_logging
from ashare.strategy import build_risk, build_strategy


def cmd_fetch(cfg: dict[str, Any]) -> int:
    panel = cache_universe(cfg)
    print(f"Cached {len(panel)} symbols")
    for sym, df in panel.items():
        print(f"  {sym}: {len(df)} bars")
    return 0 if panel else 1


def cmd_train(cfg: dict[str, Any]) -> int:
    from ashare.ml.train import train_model

    meta = train_model(cfg)
    print(json.dumps({k: v for k, v in meta.items() if k != "feature_importance"}, indent=2, ensure_ascii=False))
    print("Feature importance:")
    for name, val in sorted(meta.get("feature_importance", {}).items(), key=lambda x: -x[1]):
        print(f"  {name}: {val:.1f}")
    print(f"Model: {meta.get('model_path')}")
    return 0


def cmd_backtest(cfg: dict[str, Any]) -> int:
    panel = ensure_panel(cfg)
    if not panel:
        print("No market data. Run: python -m ashare.main fetch")
        return 1
    bt = cfg.get("backtest", {})
    trading = cfg.get("trading", {})
    root = Path(cfg["_root"])
    broker = broker_from_cfg(
        cfg,
        persist=False,
        reset=True,
        state_file=str(root / "data" / "_backtest_state.json"),
    )
    engine = BacktestEngine(
        strategy=build_strategy(cfg),
        risk=build_risk(cfg),
        broker=broker,
        execute_at=str(trading.get("execute_at", "open")),
        lot_size=int(trading.get("lot_size", 100)),
    )
    result = engine.run(panel, start=str(bt.get("start", "2022-01-01")), end=str(bt.get("end", "2024-12-31")))
    print(result.summary())
    out = root / "data" / "backtest_result.json"
    out.parent.mkdir(parents=True, exist_ok=True)
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
        "trade_log": result.trade_log,
    }
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {out}")
    note = review_backtest(cfg, payload)
    if note:
        print("\n--- AI 复盘 ---\n" + note)
    return 0


def cmd_paper(cfg: dict[str, Any]) -> int:
    panel = ensure_panel(cfg)
    if not panel:
        print("No market data. Run: python -m ashare.main fetch")
        return 1
    paper = cfg.get("paper", {})
    bt = cfg.get("backtest", {})
    trading = cfg.get("trading", {})
    reset = bool(paper.get("reset_on_start", False))
    broker = broker_from_cfg(cfg, persist=True, reset=reset)
    engine = BacktestEngine(
        strategy=build_strategy(cfg),
        risk=build_risk(cfg),
        broker=broker,
        execute_at=str(trading.get("execute_at", "open")),
        lot_size=int(trading.get("lot_size", 100)),
    )
    result = engine.run(
        panel,
        start=str(bt.get("start", "2022-01-01")),
        end=str(bt.get("end", "2024-12-31")),
        skip_until=None if reset else broker.last_date,
    )
    print(result.summary())
    print(f"Paper state: {paper.get('state_file')}")
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
    }
    note = review_backtest(cfg, payload)
    if note:
        print("\n--- AI 复盘 ---\n" + note)
    return 0


def cmd_review(cfg: dict) -> int:
    root = Path(cfg["_root"])
    path = root / "data" / "backtest_result.json"
    if not path.exists():
        print("No data/backtest_result.json — run backtest first")
        return 1
    metrics = json.loads(path.read_text(encoding="utf-8"))
    note = review_backtest(cfg, metrics)
    if not note:
        print("AI review skipped. Set AI_API_KEY in .env and ai.enabled: true")
        return 1
    print(note)
    return 0


def cmd_db_init(cfg: dict[str, Any]) -> int:
    from ashare.db.pg import database_url_from_env, init_schema
    from ashare.db.redis_client import ping_redis, redis_url_from_env

    db_url = database_url_from_env(cfg)
    print(f"Init schema: {db_url.split('@')[-1]}")
    try:
        init_schema(db_url)
        print("PostgreSQL OK")
    except Exception as exc:  # noqa: BLE001
        print(f"PostgreSQL FAILED: {exc}")
        print("请在 .env 设置正确的 DATABASE_URL（用户名/密码）")
        return 1
    rurl = redis_url_from_env(cfg)
    if ping_redis(rurl):
        print(f"Redis OK: {rurl}")
    else:
        print(f"Redis FAILED: {rurl}")
        return 1
    return 0


def cmd_research(cfg: dict[str, Any]) -> int:
    from ashare.services.research import run_research

    payload = run_research(cfg)
    print(f"as_of={payload.get('as_of')} strategy={payload.get('strategy')} pool={payload.get('universe_size')}")
    print(f"圆桌: {(payload.get('roundtable') or {}).get('summary')}")
    for p in payload.get("picks") or []:
        print(
            f"  {p.get('committee_verdict')} {p.get('name') or ''} {p.get('symbol')} "
            f"score={p.get('score')} · {p.get('ai_rationale') or p.get('why')}"
        )
    print("研报: data/reports/latest.md")
    return 0


def cmd_auto(cfg: dict[str, Any]) -> int:
    """Paper only: reset 3000 account → pick → auto buy."""
    from ashare.services.trading import run_auto_paper

    cfg.setdefault("broker", {})["mode"] = "paper"
    result = run_auto_paper(cfg, reset=True)
    acc = result.get("account") or {}
    print(f"本金: {result.get('initial_balance')}")
    print(f"选股日: {(result.get('picks') or {}).get('as_of')} 策略: {(result.get('picks') or {}).get('strategy')}")
    for p in (result.get("picks") or {}).get("picks") or []:
        print(f"  选中 {p.get('symbol')} score={p.get('score')} weight={p.get('weight')}")
    print("成交:")
    for o in result.get("orders") or []:
        print(f"  {o}")
    print(
        f"账户: cash={acc.get('cash')} equity={acc.get('equity')} "
        f"positions={acc.get('positions')}"
    )
    return 0


def cmd_serve(cfg: dict[str, Any], host: str = "127.0.0.1", port: int = 8000) -> int:
    import uvicorn

    from ashare.api.app import create_app

    app = create_app(cfg.get("_config_path"))
    print(f"API http://{host}:{port}  (web: cd web && npm run dev)")
    uvicorn.run(app, host=host, port=port, log_level="info")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="A-share leader research: factors + event pool + AI roundtable")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", default="config/default.yaml", help="YAML config path")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("fetch", parents=[common], help="Download / cache daily bars")
    sub.add_parser("train", parents=[common], help="Train LightGBM model")
    sub.add_parser("backtest", parents=[common], help="Historical backtest")
    sub.add_parser("paper", parents=[common], help="Local paper account on cached bars")
    sub.add_parser("review", parents=[common], help="LLM review of last backtest JSON")
    sub.add_parser("research", parents=[common], help="Leader pool + factors + AI roundtable report")
    sub.add_parser("db-init", parents=[common], help="Create PostgreSQL schema + ping Redis")
    sub.add_parser("auto", parents=[common], help="Paper auto: reset → research → buy (default 3000)")
    sub.add_parser("agent", parents=[common], help="One cycle: research → paper trade → optimize")
    sub.add_parser("reset", parents=[common], help="Clear paper account + PnL to initial 3000")
    serve = sub.add_parser("serve", parents=[common], help="Start FastAPI for the React UI")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    return p


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    cfg = load_config(args.config)
    mon = cfg.get("monitor", {})
    setup_logging(mon.get("log_dir", "logs"), mon.get("log_level", "INFO"), name="ashare")

    if args.command == "fetch":
        raise SystemExit(cmd_fetch(cfg))
    if args.command == "train":
        raise SystemExit(cmd_train(cfg))
    if args.command == "backtest":
        raise SystemExit(cmd_backtest(cfg))
    if args.command == "paper":
        raise SystemExit(cmd_paper(cfg))
    if args.command == "review":
        raise SystemExit(cmd_review(cfg))
    if args.command == "research":
        raise SystemExit(cmd_research(cfg))
    if args.command == "db-init":
        raise SystemExit(cmd_db_init(cfg))
    if args.command == "auto":
        raise SystemExit(cmd_auto(cfg))
    if args.command == "reset":
        from ashare.services.trading import reset_paper_account

        out = reset_paper_account(cfg)
        print(json.dumps(out, indent=2, ensure_ascii=False, default=str))
        raise SystemExit(0)
    if args.command == "agent":
        from ashare.services.agent import run_cycle

        out = run_cycle(cfg, reset_paper=False)
        print(json.dumps({k: out.get(k) for k in ("cycle", "metrics", "proposal", "train")}, indent=2, ensure_ascii=False, default=str))
        raise SystemExit(0)
    if args.command == "serve":
        raise SystemExit(cmd_serve(cfg, host=args.host, port=args.port))
    parser.error(f"Unknown command: {args.command}")


if __name__ == "__main__":
    main()
