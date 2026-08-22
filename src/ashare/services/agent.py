from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ashare.ai.optimizer import apply_proposal, persist_runtime_overrides, propose_updates
from ashare.config import load_config

logger = logging.getLogger("ashare.services.agent")

_lock = threading.Lock()
_stop = threading.Event()
_thread: threading.Thread | None = None
_state: dict[str, Any] = {
    "running": False,
    "cycle": 0,
    "phase": "idle",
    "last_error": "",
    "started_at": None,
    "logs": [],
}


def _state_path(cfg: dict[str, Any]) -> Path:
    return Path(cfg["_root"]) / "data" / "agent_state.json"


def _log(msg: str, **extra: Any) -> None:
    row = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "message": msg,
        **extra,
    }
    with _lock:
        logs = list(_state.get("logs") or [])
        logs.append(row)
        _state["logs"] = logs[-80:]
        _state["phase"] = extra.get("phase", _state.get("phase"))
    logger.info("%s %s", msg, extra)


def snapshot() -> dict[str, Any]:
    with _lock:
        return dict(_state)


def restore_state(cfg: dict[str, Any] | None = None) -> None:
    """Load last agent_state.json into memory (running flag always false until start)."""
    cfg = cfg or load_config()
    path = _state_path(cfg)
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        with _lock:
            _state["cycle"] = int(data.get("cycle") or 0)
            _state["last_result"] = data.get("last_result")
            _state["last_error"] = data.get("last_error") or ""
            _state["logs"] = list(data.get("logs") or [])[-80:]
            _state["phase"] = "idle"
            _state["running"] = False
    except Exception as exc:  # noqa: BLE001
        logger.warning("restore agent state failed: %s", exc)


def _persist(cfg: dict[str, Any]) -> None:
    path = _state_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot(), indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def _paper_metrics(cfg: dict[str, Any]) -> dict[str, Any]:
    from ashare.data.provider import latest_marks
    from ashare.services.trading import PaperTradingBroker, build_live_or_paper, snapshot_account

    broker = build_live_or_paper(cfg)
    broker.connect()
    if isinstance(broker, PaperTradingBroker):
        held = [p.symbol for p in broker.get_positions()]
        if held:
            try:
                broker.set_marks(latest_marks(cfg, held))
            except Exception as exc:  # noqa: BLE001
                logger.warning("marks failed: %s", exc)
    acc = snapshot_account(cfg, broker)
    initial = float(cfg.get("paper", {}).get("initial_balance", 3000) or 3000)
    equity = float(acc.get("equity") or 0)
    acc["paper_return"] = (equity / initial - 1.0) if initial else 0.0
    acc["initial_balance"] = initial
    return acc


def run_cycle(cfg: dict[str, Any], *, reset_paper: bool = False, do_retrain: bool | None = None) -> dict[str, Any]:
    """One autonomous cycle: pick → paper trade → evaluate → LLM optimize → optional retrain."""
    cfg.setdefault("broker", {})["mode"] = "paper"
    import os

    os.environ["BROKER_MODE"] = "paper"
    from ashare.ml.train import train_model
    from ashare.services.picks import run_picks
    from ashare.services.trading import execute_picks

    with _lock:
        _state["cycle"] = int(_state.get("cycle") or 0) + 1
        cycle = _state["cycle"]
    cycle_id = f"agent_{cycle}"
    try:
        from ashare.ai.cost_tracker import get_cost_tracker

        get_cost_tracker(cfg).begin_cycle(cycle_id)
    except Exception as exc:  # noqa: BLE001
        logger.debug("cost tracker begin_cycle skipped: %s", exc)
    _log("开始第 %d 轮" % cycle, phase="start", cycle=cycle)

    picks: dict[str, Any] = {}
    if reset_paper:
        from ashare.services.trading import run_auto_paper

        _log("重置模拟账户并买入", phase="trade")
        traded = run_auto_paper(cfg, reset=True)
    else:
        _log("构建龙头/事件池并因子打分", phase="picks")
        picks = run_picks(cfg)
        _log(
            "候选 %d 只 · 池来源 %s"
            % (
                len(picks.get("picks") or []),
                (picks.get("screen") or {}).get("sources") or picks.get("universe_mode"),
            ),
            phase="picks",
            picks=[p.get("name") or p.get("symbol") for p in (picks.get("picks") or [])],
        )
        rt = picks.get("roundtable") or {}
        if rt:
            _log(
                "投委会圆桌：%s" % (rt.get("summary") or rt.get("source") or "完成"),
                phase="roundtable",
            )
            for r in rt.get("reviews") or []:
                _log(
                    "%s %s：%s"
                    % (
                        r.get("committee_verdict") or ("通过" if r.get("ai_approve") else "拒绝"),
                        r.get("name") or r.get("symbol"),
                        r.get("ai_rationale") or r.get("committee_thesis") or "",
                    ),
                    phase="roundtable",
                    symbol=r.get("symbol"),
                    verdict=r.get("committee_verdict"),
                )
        _log("按圆桌 buy 结论模拟交易", phase="review")
        traded = execute_picks(cfg, regenerate=False, force_live=False)
        ai_rev = traded.get("ai_review") or (traded.get("picks") or {}).get("ai_review") or {}
        for r in ai_rev.get("reviews") or []:
            flag = r.get("committee_verdict") or ("通过" if r.get("ai_approve") else "拒绝")
            _log(
                "%s %s：%s" % (flag, r.get("name") or r.get("symbol"), r.get("ai_rationale") or ""),
                phase="review",
                symbol=r.get("symbol"),
                approve=r.get("ai_approve"),
            )
        if traded.get("ai_rejected_all"):
            _log(str(traded.get("message") or "投委会未给出 buy，本轮不买"), phase="review")
        elif traded.get("skipped_buy"):
            _log(str(traded.get("message") or "现金不足，本轮只持仓评估"), phase="trade")
        else:
            _log(
                "模拟买入 %d 笔" % len(traded.get("orders") or []),
                phase="trade",
                orders=[o.get("symbol") for o in (traded.get("orders") or []) if o.get("ok")],
            )

    acc = traded.get("account") or _paper_metrics(cfg)
    initial = float(cfg.get("paper", {}).get("initial_balance", 3000) or 3000)
    equity = float(acc.get("equity") or 0)
    metrics = {
        "paper_return": (equity / initial - 1.0) if initial else 0.0,
        "equity": equity,
        "cash": acc.get("cash"),
        "positions": [
            {"symbol": p.get("symbol"), "name": p.get("name"), "shares": p.get("shares"), "cost": p.get("cost_price")}
            for p in (acc.get("positions") or [])
        ],
        "orders": [
            {"symbol": o.get("symbol"), "ok": o.get("ok"), "message": o.get("message"), "quantity": o.get("quantity")}
            for o in (traded.get("orders") or [])
        ],
        "picks": traded.get("picks", {}).get("picks") if isinstance(traded.get("picks"), dict) else None,
        "roundtable": (traded.get("picks") or {}).get("roundtable")
        if isinstance(traded.get("picks"), dict)
        else (picks.get("roundtable") if isinstance(picks, dict) else None),
        "ai_review": traded.get("ai_review")
        or ((traded.get("picks") or {}).get("ai_review") if isinstance(traded.get("picks"), dict) else None),
        "style": "leader",
        "top_n": cfg.get("strategy", {}).get("top_n"),
    }
    _log(
        "权益 %.2f 收益 %.2f%%" % (equity, metrics["paper_return"] * 100),
        phase="evaluate",
        equity=equity,
        paper_return=metrics["paper_return"],
    )
    try:
        from ashare.services.pnl import record_equity

        record_equity(cfg, equity=equity, cash=acc.get("cash"), source="agent")
    except Exception as exc:  # noqa: BLE001
        logger.warning("record pnl failed: %s", exc)

    _log("AI 优化龙头因子/池参数", phase="optimize")
    proposal = propose_updates(
        cfg,
        {
            "metrics": metrics,
            "current_strategy": cfg.get("strategy"),
            "pool": cfg.get("pool"),
            "factors": cfg.get("factors"),
            "roundtable_summary": (metrics.get("roundtable") or {}).get("summary")
            if isinstance(metrics.get("roundtable"), dict)
            else None,
            "ml": {k: cfg.get("ml", {}).get(k) for k in ("top_n", "label_horizon", "n_estimators")},
        },
    )
    persist_runtime_overrides(cfg["_root"], proposal)
    cfg = apply_proposal(cfg, proposal)
    _log(str(proposal.get("rationale") or "已更新参数"), phase="optimize", proposal=proposal)

    should_train = do_retrain if do_retrain is not None else bool(proposal.get("retrain"))
    train_meta = None
    if should_train:
        _log("按新参数重训 LightGBM", phase="train")
        try:
            overrides = {}
            if "n_estimators" in proposal:
                overrides["n_estimators"] = proposal["n_estimators"]
            if "label_horizon" in proposal:
                overrides["label_horizon"] = proposal["label_horizon"]
            if "num_leaves" in proposal:
                overrides["num_leaves"] = proposal["num_leaves"]
            if "learning_rate" in proposal:
                overrides["learning_rate"] = proposal["learning_rate"]
            train_meta = train_model(cfg, overrides=overrides or None)
            _log("训练完成 IC=%.4f" % float(train_meta.get("ic") or 0), phase="train", ic=train_meta.get("ic"))
        except Exception as exc:  # noqa: BLE001
            _log("训练失败，沿用旧模型: %s" % exc, phase="train")

    result = {
        "cycle": cycle,
        "metrics": metrics,
        "proposal": proposal,
        "train": {k: train_meta.get(k) for k in ("run_id", "ic", "mse") if train_meta} if train_meta else None,
        "account": acc,
        "picks": traded.get("picks"),
        "orders": traded.get("orders"),
        "roundtable": (traded.get("picks") or {}).get("roundtable") if isinstance(traded.get("picks"), dict) else None,
        "ai_review": traded.get("ai_review") or (traded.get("picks") or {}).get("ai_review"),
    }
    try:
        from ashare.ai.cost_tracker import get_cost_tracker

        result["ai_cost"] = get_cost_tracker(cfg).cycle_summary(cycle_id)
    except Exception as exc:  # noqa: BLE001
        logger.debug("cost summary skipped: %s", exc)
    with _lock:
        _state["last_result"] = result
        _state["last_error"] = ""
        _state["phase"] = "idle" if not _state.get("running") else "waiting"
    _persist(cfg)
    return result


def _loop(interval_sec: float) -> None:
    while not _stop.is_set():
        try:
            cfg = load_config()
            cfg.setdefault("broker", {})["mode"] = "paper"
            run_cycle(cfg, reset_paper=False)
        except Exception as exc:  # noqa: BLE001
            logger.exception("agent cycle failed")
            with _lock:
                _state["last_error"] = str(exc)
                _state["phase"] = "error"
            _log("本轮失败: %s" % exc, phase="error")
        waited = 0.0
        while waited < interval_sec and not _stop.is_set():
            time.sleep(min(2.0, interval_sec - waited))
            waited += 2.0
        if _stop.is_set():
            break
    with _lock:
        _state["running"] = False
        _state["phase"] = "stopped"


def start_agent(*, interval_sec: float | None = None, run_now: bool = True) -> dict[str, Any]:
    global _thread
    cfg = load_config()
    sec = float(interval_sec or cfg.get("agent", {}).get("interval_sec") or 3600)
    with _lock:
        if _state.get("running") and _thread and _thread.is_alive():
            return snapshot()
        _stop.clear()
        _state["running"] = True
        _state["phase"] = "starting"
        _state["started_at"] = datetime.now(timezone.utc).isoformat()
        _state["last_error"] = ""
        _state["interval_sec"] = sec

    def target():
        if run_now:
            try:
                run_cycle(load_config(), reset_paper=False)
            except Exception as exc:  # noqa: BLE001
                with _lock:
                    _state["last_error"] = str(exc)
                _log("首轮失败: %s" % exc, phase="error")
        _loop(sec)

    _thread = threading.Thread(target=target, name="ashare-agent", daemon=True)
    _thread.start()
    _log("AI 自主循环已启动，间隔 %ss" % int(sec), phase="starting")
    return snapshot()


def stop_agent() -> dict[str, Any]:
    _stop.set()
    with _lock:
        _state["running"] = False
        _state["phase"] = "stopping"
    _log("收到停止指令", phase="stopping")
    return snapshot()


def reset_and_restart(*, interval_sec: float | None = None) -> dict[str, Any]:
    """Stop agent, wipe paper/pnl, start a fresh cycle with full capital."""
    stop_agent()
    time.sleep(0.3)
    cfg = load_config()
    from ashare.services.trading import reset_paper_account

    cleared = reset_paper_account(cfg)
    with _lock:
        _state.clear()
        _state.update(
            {
                "running": False,
                "cycle": 0,
                "phase": "idle",
                "last_error": "",
                "started_at": None,
                "logs": [],
            }
        )
    _log("账户与盈亏已清空，本金 %.0f" % float(cleared.get("cash") or 3000), phase="reset")
    return {**start_agent(interval_sec=interval_sec, run_now=True), "reset": cleared}
