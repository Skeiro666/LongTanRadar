from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("ashare.services.pnl")


def _path(cfg: dict[str, Any]) -> Path:
    return Path(cfg["_root"]) / "data" / "pnl_curve.json"


def _load(cfg: dict[str, Any]) -> dict[str, Any]:
    path = _path(cfg)
    if not path.exists():
        return {"initial_balance": float(cfg.get("paper", {}).get("initial_balance", 3000)), "points": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("load pnl curve failed: %s", exc)
        return {"initial_balance": float(cfg.get("paper", {}).get("initial_balance", 3000)), "points": []}


def _save(cfg: dict[str, Any], payload: dict[str, Any]) -> None:
    path = _path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def record_equity(
    cfg: dict[str, Any],
    *,
    equity: float,
    cash: float | None = None,
    source: str = "agent",
) -> dict[str, Any]:
    """Append a mark; same calendar day keeps the latest equity for daily chart."""
    initial = float(cfg.get("paper", {}).get("initial_balance", 3000) or 3000)
    payload = _load(cfg)
    payload["initial_balance"] = initial
    points: list[dict[str, Any]] = list(payload.get("points") or [])
    day = date.today().isoformat()
    now = datetime.now(timezone.utc).isoformat()
    row = {
        "date": day,
        "ts": now,
        "equity": float(equity),
        "cash": float(cash) if cash is not None else None,
        "pnl_total": float(equity) - initial,
        "return_total": (float(equity) / initial - 1.0) if initial else 0.0,
        "source": source,
    }
    # replace last point of same day
    if points and points[-1].get("date") == day:
        points[-1] = row
    else:
        points.append(row)
    # compute day pnl vs previous day close
    if len(points) >= 2:
        prev = float(points[-2]["equity"])
        points[-1]["pnl_day"] = float(equity) - prev
        points[-1]["return_day"] = (float(equity) / prev - 1.0) if prev else 0.0
    else:
        points[-1]["pnl_day"] = float(equity) - initial
        points[-1]["return_day"] = points[-1]["return_total"]
    payload["points"] = points[-400:]
    payload["updated_at"] = now
    _save(cfg, payload)
    return payload


def pnl_summary(cfg: dict[str, Any]) -> dict[str, Any]:
    payload = _load(cfg)
    points = list(payload.get("points") or [])
    initial = float(payload.get("initial_balance") or cfg.get("paper", {}).get("initial_balance", 3000) or 3000)
    if not points:
        # seed so chart has a start
        points = [
            {
                "date": date.today().isoformat(),
                "equity": initial,
                "pnl_day": 0.0,
                "pnl_total": 0.0,
                "return_day": 0.0,
                "return_total": 0.0,
            }
        ]
    last = points[-1]
    curve = [
        {
            "date": p["date"],
            "equity": float(p["equity"]),
            "pnl_day": float(p.get("pnl_day") or 0),
            "pnl_total": float(p.get("pnl_total") or (float(p["equity"]) - initial)),
            "return_day": float(p.get("return_day") or 0),
            "return_total": float(p.get("return_total") or 0),
        }
        for p in points
    ]
    out = {
        "initial_balance": initial,
        "equity": float(last["equity"]),
        "pnl_day": float(last.get("pnl_day") or 0),
        "pnl_total": float(last.get("pnl_total") or (float(last["equity"]) - initial)),
        "return_day": float(last.get("return_day") or 0),
        "return_total": float(last.get("return_total") or 0),
        "as_of": last.get("date"),
        "curve": curve,
        "updated_at": payload.get("updated_at"),
        "truth_model": {
            "account_pnl": "paper_broker_equity",
            "per_symbol_alpha": "research_outcomes.primary_horizons",
            "note": "Portfolio equity from paper account; attribution alpha from latest research outcomes.",
        },
    }
    out.update(_research_alpha_link(cfg))
    return out


def _research_alpha_link(cfg: dict[str, Any]) -> dict[str, Any]:
    try:
        from ashare.services.research import latest_research

        research = latest_research(cfg) or {}
        pack = research.get("research_outcomes") or {}
        if not pack.get("available"):
            return {"research_link": {"available": False}}
        return {
            "research_link": {
                "available": True,
                "research_as_of": research.get("as_of"),
                "horizon": pack.get("horizon"),
                "benchmark_snapshot": pack.get("benchmark_snapshot"),
                "portfolio_attribution": pack.get("portfolio_attribution"),
                "ai_incremental_alpha": pack.get("ai_incremental_alpha"),
                "outcome_truth": pack.get("outcome_truth"),
            }
        }
    except Exception as exc:  # noqa: BLE001
        logger.debug("research alpha link skipped: %s", exc)
        return {"research_link": {"available": False, "note": "research_unavailable"}}
