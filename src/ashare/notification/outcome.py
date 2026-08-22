from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from ashare.config_loaders import load_yaml_config
from ashare.symbols import to_symbol


def _cfg(cfg: dict[str, Any] | None) -> dict[str, Any]:
    return load_yaml_config(cfg, "notification")


def seed_notification_outcome(cfg: dict[str, Any], notification_row: dict[str, Any], inp: Any) -> dict[str, Any]:
    """Create outcome tracking row at notification send time."""
    from ashare.notification.store import NotificationStore
    from ashare.research.signal_attribution import resolve_primary_source

    meta = notification_row.get("metadata") or {}
    canonical = inp.canonical if hasattr(inp, "canonical") else {}
    snap = inp.snapshot if hasattr(inp, "snapshot") else {}
    eer = dict(meta.get("expected_excess_return") or {})
    if not eer.get("available"):
        eer_meta = dict((snap.get("candidate_score_meta") or {}).get("expected_excess_return") or {})
        eer = eer_meta if eer_meta.get("available") else eer
    srcs = meta.get("candidate_sources") or canonical.get("candidate_sources") or []
    resolved = resolve_primary_source(srcs, attribution_cfg(cfg).get("primary_source_priority"))

    outcome = {
        "notification_id": notification_row.get("notification_id"),
        "decision_id": notification_row.get("decision_id"),
        "research_session_id": notification_row.get("research_session_id"),
        "symbol": notification_row.get("symbol"),
        "level": notification_row.get("level"),
        "decision": canonical.get("research_rating") or notification_row.get("level"),
        "confidence": meta.get("confidence") or canonical.get("confidence"),
        "expected_excess_return": eer,
        "notify_time": notification_row.get("sent_at") or notification_row.get("created_at"),
        "notify_price": meta.get("notify_price"),
        "entry_type": "notify_price",
        "candidate_sources": srcs,
        "primary_source": resolved["primary_source"],
        "secondary_sources": resolved["secondary_sources"],
        "horizons": {},
        "status": "tracking",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    NotificationStore(cfg).append_outcome(outcome)
    return outcome


def attribution_cfg(cfg: dict[str, Any] | None) -> dict[str, Any]:
    from ashare.research.signal_attribution import attribution_cfg as _acfg

    return _acfg(cfg)


def refresh_notification_outcomes(cfg: dict[str, Any], panel: dict[str, pd.DataFrame] | None = None) -> dict[str, Any]:
    """Update T+1/5/10/20 returns from notify_price entry."""
    from ashare.notification.store import NotificationStore
    from ashare.research.benchmark import resolve_dual_benchmark_pack

    store = NotificationStore(cfg)
    outcomes = store.list_outcomes()
    if not outcomes:
        return {"available": False, "n": 0}

    if panel is None:
        from ashare.data.provider import ensure_panel

        syms = list({to_symbol(o["symbol"]) for o in outcomes if o.get("symbol")})
        panel = ensure_panel(cfg, syms)

    n_cfg = _cfg(cfg)
    horizons = list((n_cfg.get("outcome") or {}).get("horizons_days") or [1, 5, 10, 20])
    min_sample = int((n_cfg.get("outcome") or {}).get("minimum_sample") or 5)

    as_of = pd.Timestamp.now().normalize()
    bench_pack = resolve_dual_benchmark_pack(cfg, panel, as_of, horizons=horizons)
    mkt = bench_pack.get("market_returns") or {}
    uni = bench_pack.get("universe_returns") or {}

    updated: list[dict[str, Any]] = []
    for o in outcomes:
        sym = to_symbol(o.get("symbol") or "")
        df = panel.get(sym)
        notify_time = pd.Timestamp(str(o.get("notify_time") or "")[:19])
        entry = o.get("notify_price")
        if df is None or df.empty or entry is None:
            updated.append(o)
            continue
        try:
            entry = float(entry)
        except (TypeError, ValueError):
            updated.append(o)
            continue

        df = df.copy()
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date")
        hist = df[df["date"] <= notify_time]
        if hist.empty:
            updated.append(o)
            continue
        if entry <= 0:
            entry = float(hist.iloc[-1]["close"])
        fut = df[df["date"] > notify_time]
        hz: dict[str, Any] = {}
        for h in horizons:
            h_key = str(h)
            if len(fut) < h:
                hz[h_key] = {"status": "pending"}
                continue
            px = float(fut.iloc[h - 1]["close"])
            ret = px / entry - 1.0
            mkt_b = float(mkt[h_key]) if h_key in mkt and mkt[h_key] is not None else None
            uni_b = float(uni[h_key]) if h_key in uni and uni[h_key] is not None else None
            hz[h_key] = {
                "realized_return": ret,
                "benchmark_return": mkt_b,
                "market_alpha": (ret - mkt_b) if mkt_b is not None else None,
                "selection_alpha": (ret - uni_b) if uni_b is not None else None,
                "status": "ok",
            }
        o = {**o, "horizons": hz, "entry_price": entry, "status": "updated"}
        updated.append(o)

    # rewrite outcomes file
    path = store.outcome_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(u, ensure_ascii=False, default=str) for u in updated) + ("\n" if updated else ""),
        encoding="utf-8",
    )

    attr = compute_notification_attribution(updated, horizons=horizons, minimum_sample=min_sample)
    disc = compute_discovery_attribution(updated, horizons=horizons, minimum_sample=min_sample)
    return {"available": True, "n": len(updated), "notification_attribution": attr, "discovery_attribution": disc}


def compute_notification_attribution(
    outcomes: list[dict[str, Any]],
    *,
    horizons: list[int] | None = None,
    minimum_sample: int = 5,
) -> dict[str, Any]:
    horizons = horizons or [1, 5, 10, 20]
    levels = ["BUY", "STRONG_BUY", "RISK_EXIT"]
    out: dict[str, Any] = {}
    for level in levels:
        rows = [o for o in outcomes if str(o.get("level") or "").upper() == level]
        out[level] = {}
        for h in horizons:
            h_key = str(h)
            rets, mkt, sel = [], [], []
            for o in rows:
                cell = (o.get("horizons") or {}).get(h_key) or {}
                if cell.get("status") != "ok":
                    continue
                if cell.get("realized_return") is not None:
                    rets.append(float(cell["realized_return"]))
                if cell.get("market_alpha") is not None:
                    mkt.append(float(cell["market_alpha"]))
                if cell.get("selection_alpha") is not None:
                    sel.append(float(cell["selection_alpha"]))
            n = len(rets)
            if n < minimum_sample:
                out[level][h_key] = {
                    "insufficient_sample": True,
                    "sample_count": n,
                    "minimum_sample": minimum_sample,
                }
            else:
                out[level][h_key] = {
                    "insufficient_sample": False,
                    "sample_count": n,
                    "mean_realized_return": sum(rets) / n,
                    "mean_market_alpha": sum(mkt) / len(mkt) if mkt else None,
                    "mean_selection_alpha": sum(sel) / len(sel) if sel else None,
                }
    return out


def compute_discovery_attribution(
    outcomes: list[dict[str, Any]],
    *,
    horizons: list[int] | None = None,
    minimum_sample: int = 5,
) -> dict[str, Any]:
    horizons = horizons or [1, 5, 10, 20]
    tags = ["quant", "news", "event", "profit", "ml", "ai"]
    out: dict[str, Any] = {}
    for tag in tags:
        out[tag] = {}
        for h in horizons:
            h_key = str(h)
            mkt, sel = [], []
            for o in outcomes:
                sources = [str(s).lower() for s in (o.get("candidate_sources") or [])]
                if tag not in sources:
                    continue
                cell = (o.get("horizons") or {}).get(h_key) or {}
                if cell.get("status") != "ok":
                    continue
                if cell.get("market_alpha") is not None:
                    mkt.append(float(cell["market_alpha"]))
                if cell.get("selection_alpha") is not None:
                    sel.append(float(cell["selection_alpha"]))
            n = len(mkt) or len(sel)
            if n < minimum_sample:
                out[tag][h_key] = {"insufficient_sample": True, "sample_count": n, "minimum_sample": minimum_sample}
            else:
                out[tag][h_key] = {
                    "insufficient_sample": False,
                    "sample_count": n,
                    "mean_market_alpha": sum(mkt) / len(mkt) if mkt else None,
                    "mean_selection_alpha": sum(sel) / len(sel) if sel else None,
                }
    return out
