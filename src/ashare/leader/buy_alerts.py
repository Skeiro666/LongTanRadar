from __future__ import annotations

from typing import Any

from ashare.config_loaders import load_yaml_config
from ashare.symbols import to_symbol


def build_buy_ready_alerts(
    cfg: dict[str, Any],
    *,
    universe: list[dict[str, Any]],
    decisions: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """
    Paper/manual BUY_ALERT candidates.
    Requires TradeTiming BUY_READY + risk pass (if require_risk_pass).
    Does not auto-trade. research_only cycles still emit alerts for UI/audit.
    """
    lc = load_yaml_config(cfg, "leader")
    ncfg = dict(lc.get("notification") or {})
    if not ncfg.get("buy_ready_alert", True):
        return []
    require_risk = bool(ncfg.get("require_risk_pass", True))
    by_sym = {to_symbol(d.get("symbol") or ""): d for d in (decisions or []) if d.get("symbol")}
    alerts: list[dict[str, Any]] = []
    for row in universe:
        if str(row.get("trade_timing_action") or "").upper() != "BUY_READY":
            continue
        if str(row.get("lifecycle") or "").upper() == "DROPPED":
            continue
        sym = to_symbol(row.get("symbol") or "")
        cd = by_sym.get(sym) or {}
        risk = str(cd.get("risk_status") or "pass").lower()
        if require_risk and cd and risk not in {"pass", ""}:
            continue
        alerts.append(
            {
                "alert_type": "BUY_ALERT",
                "symbol": sym,
                "name": row.get("name") or cd.get("name"),
                "price": row.get("close") or row.get("price"),
                "board_count": row.get("board_count"),
                "leader_score": row.get("leader_score"),
                "stage": row.get("stage"),
                "chase_score": row.get("chase_score"),
                "chase_level": row.get("chase_level"),
                "trade_timing_score": row.get("trade_timing_score"),
                "trade_timing_action": row.get("trade_timing_action"),
                "reentry_score": row.get("reentry_score"),
                "reentry_phase": row.get("reentry_phase"),
                "focus_tier": row.get("focus_tier"),
                "news_score": row.get("news_score"),
                "risk_score": cd.get("risk_status"),
                "risk_flags": cd.get("risk_flags"),
                "buy_reason": row.get("status_reason") or row.get("timing_reason"),
                "main_risks": cd.get("committee_risks") or row.get("drop_reason"),
                "suggested_weight": cd.get("weight"),
                "trigger_time": row.get("as_of") or cd.get("as_of"),
                "entry_timeline": row.get("entry_timeline"),
                "research_only": bool(lc.get("research_only", True)),
                "auto_trade": False,
            }
        )
    return alerts
