from __future__ import annotations

from typing import Any

from ashare.notification.store import NotificationStore
from ashare.research.signal_attribution import horizon_metrics, minimum_sample_size


def build_notification_history(cfg: dict[str, Any] | None = None, *, limit: int = 100) -> dict[str, Any]:
    store = NotificationStore(cfg)
    notes = store.list_recent(limit)
    outcomes = store.list_outcomes(limit * 2)
    by_nid = {str(o.get("notification_id")): o for o in outcomes if o.get("notification_id")}
    min_n = minimum_sample_size(cfg)
    rows: list[dict[str, Any]] = []
    for n in notes:
        oid = str(n.get("notification_id") or "")
        out = by_nid.get(oid) or {}
        hz: dict[str, Any] = {}
        for h in (1, 5, 10, 20):
            m = horizon_metrics(out, h) if out else None
            if not m:
                hz[str(h)] = {"available": False}
            else:
                ex = m.get("selection_alpha") or m.get("market_alpha")
                hz[str(h)] = {
                    "available": True,
                    "return": m.get("realized_return"),
                    "excess_return": ex,
                }
        rows.append(
            {
                **n,
                "outcome": out or None,
                "horizons": hz,
                "outcome_status": out.get("status") if out else "PENDING",
                "research_snapshot_id": n.get("research_session_id") or n.get("research_id"),
            }
        )
    return {
        "n": len(rows),
        "minimum_sample_size": min_n,
        "notifications": rows,
        "note": "Per-notification outcomes when available; aggregate stats on /api/notifications/stats",
    }
