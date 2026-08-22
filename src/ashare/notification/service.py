from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from ashare.config_loaders import load_yaml_config
from ashare.notification.channels.email import send_email
from ashare.notification.channels.wechat import send_wechat
from ashare.notification.dedup import DedupStore, apply_dedup
from ashare.notification.formatter import format_notification
from ashare.notification.gate import NotificationGate, _event_id, rank_and_cap
from ashare.notification.models import (
    GATE_NOTIFY,
    GATE_SKIP,
    STATUS_COOLDOWN,
    STATUS_DISABLED,
    STATUS_DUPLICATE,
    STATUS_FAILED,
    STATUS_SENT,
    STATUS_SKIPPED,
    GateInput,
)
from ashare.notification.store import NotificationStore
from ashare.symbols import to_symbol

logger = logging.getLogger(__name__)


def _cfg(cfg: dict[str, Any] | None) -> dict[str, Any]:
    return load_yaml_config(cfg, "notification")


def _load_snapshot(cfg: dict[str, Any], research_id: str) -> dict[str, Any] | None:
    from ashare.research.snapshot import SnapshotStore

    root = cfg.get("_root")
    path = SnapshotStore(cfg).dir / f"{research_id}.json"
    if not path.exists():
        return None
    import json

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _paper_positions(cfg: dict[str, Any]) -> set[str]:
    try:
        from ashare.services.trading import build_live_or_paper

        broker = build_live_or_paper(cfg)
        broker.connect()
        return {to_symbol(p.symbol) for p in broker.get_positions() if getattr(p, "quantity", 0) > 0}
    except Exception:  # noqa: BLE001
        return set()


def _previous_decision(store: NotificationStore, symbol: str) -> str | None:
    last = store.last_sent_for_symbol(symbol)
    if not last:
        return None
    meta = last.get("metadata") or {}
    return str(meta.get("current_decision") or last.get("level") or "")


def evaluate_cycle(
    cfg: dict[str, Any],
    payload: dict[str, Any],
) -> list[dict[str, Any]]:
    """Run gate + dedup + priority cap. Returns list of send jobs."""
    n_cfg = _cfg(cfg)
    if not n_cfg.get("enabled", True):
        return []

    gate = NotificationGate(cfg)
    store = NotificationStore(cfg)
    history = store.list_recent(limit=500)
    dedup = DedupStore(history, cfg)

    canonical = list(payload.get("canonical_decisions") or [])
    reports = {to_symbol(r["symbol"]): r for r in (payload.get("platform_reports") or []) if r.get("symbol")}
    held = _paper_positions(cfg)

    candidates: list[tuple[GateInput, Any]] = []
    for cd in canonical:
        sym = to_symbol(cd.get("symbol") or "")
        if not sym:
            continue
        rep = reports.get(sym) or {}
        rid = str(cd.get("research_session_id") or cd.get("research_id") or "")
        snap = _load_snapshot(cfg, rid) if rid else None
        prev = _previous_decision(store, sym)
        inp = GateInput(
            canonical=cd,
            snapshot=snap,
            report=rep,
            has_paper_position=sym in held,
            previous_decision=prev,
        )
        gr = gate.evaluate(inp)
        evt = _event_id(snap, rep)
        gr = apply_dedup(
            gr,
            dedup,
            symbol=sym,
            event_id=evt,
            previous_decision=prev,
            current_decision=str(cd.get("research_rating") or ""),
        )
        candidates.append((inp, gr))

    max_n = int((n_cfg.get("priority") or {}).get("max_per_cycle", 3))
    selected = rank_and_cap(candidates, max_n)

    jobs: list[dict[str, Any]] = []
    for inp, gr in selected:
        if gr.action != GATE_NOTIFY:
            continue
        text = format_notification(
            level=gr.level or "",
            canonical=inp.canonical,
            snapshot=inp.snapshot,
            report=inp.report,
            cfg=cfg,
        )
        jobs.append(
            {
                "inp": inp,
                "gate": gr,
                "text": text,
                "subject": f"LongTanRadar {gr.level} — {inp.canonical.get('name') or inp.canonical.get('symbol')}",
            }
        )

    # Record SKIPPED/DUPLICATE/COOLDOWN for audit
    for inp, gr in candidates:
        if gr.action == GATE_SKIP and gr.reason in {STATUS_DUPLICATE, STATUS_COOLDOWN}:
            rec = store.make_record(
                canonical=inp.canonical,
                level=gr.level or str(inp.canonical.get("research_rating") or ""),
                channel="none",
                status=gr.reason,
                dedup_key=gr.dedup_key,
                metadata=gr.metadata,
            )
            store.append(rec)

    return jobs


def _send_job(cfg: dict[str, Any], job: dict[str, Any], cycle_id: str | None) -> list[dict[str, Any]]:
    store = NotificationStore(cfg)
    inp = job["inp"]
    gr = job["gate"]
    text = job["text"]
    subject = job["subject"]
    canonical = inp.canonical
    results: list[dict[str, Any]] = []

    for channel in gr.channels:
        if channel == "wechat":
            send_result = send_wechat(text, cfg)
        elif channel == "email":
            send_result = send_email(subject, text, cfg)
        else:
            send_result = {"ok": False, "skipped": True, "reason": f"unknown_channel_{channel}"}

        if send_result.get("skipped"):
            status = STATUS_DISABLED
        elif send_result.get("ok"):
            status = STATUS_SENT
        else:
            status = STATUS_FAILED

        meta = {
            **gr.metadata,
            "cycle_id": cycle_id,
            "event_id": _event_id(inp.snapshot, inp.report),
            "notify_price": _notify_price(inp),
            "candidate_sources": canonical.get("candidate_sources") or [],
            "confidence": canonical.get("confidence"),
            "expected_excess_return": gr.metadata.get("expected_excess_return"),
        }
        rec = store.make_record(
            canonical=canonical,
            level=gr.level or "",
            channel=channel,
            status=status,
            dedup_key=gr.dedup_key,
            metadata=meta,
            error=send_result.get("error") or send_result.get("reason"),
        )
        if status == STATUS_SENT:
            rec.sent_at = datetime.now(timezone.utc).isoformat()
        row = store.append(rec)
        results.append(row)

        if status == STATUS_SENT:
            try:
                from ashare.notification.outcome import seed_notification_outcome

                seed_notification_outcome(cfg, row, inp)
            except Exception as exc:  # noqa: BLE001
                logger.debug("notification outcome seed skipped: %s", exc)

    return results


def _notify_price(inp: GateInput) -> float | None:
    snap = inp.snapshot or {}
    market = snap.get("market") or (inp.report or {}).get("snapshot", {}).get("market") or {}
    try:
        return float(market.get("price") or market.get("close"))
    except (TypeError, ValueError):
        return None


def run_notification_job(cfg: dict[str, Any], payload: dict[str, Any], cycle_id: str | None = None) -> dict[str, Any]:
    """Synchronous notification dispatch — 0 LLM."""
    jobs = evaluate_cycle(cfg, payload)
    sent = []
    for job in jobs:
        sent.extend(_send_job(cfg, job, cycle_id))
    skipped = sum(1 for r in sent if r.get("status") in {STATUS_SKIPPED, STATUS_DISABLED})
    failed = sum(1 for r in sent if r.get("status") == STATUS_FAILED)
    ok = sum(1 for r in sent if r.get("status") == STATUS_SENT)
    return {
        "jobs": len(jobs),
        "sent": ok,
        "failed": failed,
        "skipped": skipped,
        "records": sent,
        "llm_calls": 0,
        "tokens": 0,
    }


def schedule_notification_job(cfg: dict[str, Any], payload: dict[str, Any], cycle_id: str | None = None) -> None:
    """Fire-and-forget async notification — research success not blocked."""
    n_cfg = _cfg(cfg)
    if not n_cfg.get("enabled", True):
        return
    if not n_cfg.get("async", {}).get("enabled", True):
        run_notification_job(cfg, payload, cycle_id)
        return

    def _worker() -> None:
        try:
            result = run_notification_job(cfg, payload, cycle_id)
            logger.info(
                "notification job done cycle=%s sent=%s failed=%s",
                cycle_id,
                result.get("sent"),
                result.get("failed"),
            )
            try:
                from ashare.notification.production import record_production_cycle

                record_production_cycle(cfg, payload, cycle_id, notification_result=result)
            except Exception as exc:  # noqa: BLE001
                logger.debug("production validation skipped: %s", exc)
        except Exception as exc:  # noqa: BLE001
            logger.warning("notification job failed (research unaffected): %s", exc)

    threading.Thread(target=_worker, daemon=True, name="notification-job").start()


def notification_status_for_symbol(cfg: dict[str, Any], symbol: str, research_id: str | None = None) -> dict[str, Any]:
    store = NotificationStore(cfg)
    sym = to_symbol(symbol)
    for row in store.list_recent(100):
        if row.get("symbol") != sym:
            continue
        if research_id and row.get("research_session_id") != research_id:
            continue
        if row.get("status") == STATUS_SENT:
            return {
                "notified": True,
                "notification_time": row.get("sent_at") or row.get("created_at"),
                "channel": row.get("channel"),
                "level": row.get("level"),
                "notification_id": row.get("notification_id"),
            }
    return {"notified": False}
