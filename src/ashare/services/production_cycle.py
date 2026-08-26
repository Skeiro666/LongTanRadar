"""Production cycle identity, report persistence without overwrite, live observations."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

logger = logging.getLogger("ashare.production.cycle")


def new_run_id(when: datetime | None = None) -> str:
    when = when or datetime.now(timezone.utc)
    local = when.astimezone() if when.tzinfo else when
    return f"{local.strftime('%Y%m%dT%H%M%S')}-{uuid4().hex[:8]}"


def idempotency_key(trading_date: str, cycle_type: str, scheduled_slot: str) -> str:
    return f"{trading_date}|{cycle_type}|{scheduled_slot}"


class IdempotencyStore:
    """Persist completed scheduler slots so restarts do not re-fire the same slot."""

    def __init__(self, cfg: dict[str, Any] | None = None) -> None:
        root = Path((cfg or {}).get("_root") or Path.cwd())
        self.path = root / "data" / "cache" / "scheduler_idempotency.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"completed": {}}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return {"completed": {}}

    def _save(self, data: dict[str, Any]) -> None:
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def is_done(self, key: str) -> bool:
        return key in (self._load().get("completed") or {})

    def mark_done(self, key: str, *, run_id: str, meta: dict[str, Any] | None = None) -> None:
        data = self._load()
        completed = dict(data.get("completed") or {})
        completed[key] = {
            "run_id": run_id,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            **(meta or {}),
        }
        # retain last ~90 days keys only (approx by count)
        if len(completed) > 500:
            items = sorted(completed.items(), key=lambda kv: str(kv[1].get("completed_at") or ""))
            completed = dict(items[-400:])
        data["completed"] = completed
        self._save(data)

    def get(self, key: str) -> dict[str, Any] | None:
        return (self._load().get("completed") or {}).get(key)


def persist_production_report(cfg: dict[str, Any], payload: dict[str, Any]) -> Path:
    """
    Never overwrite prior runs for the same as_of.
    Layout:
      data/reports/{as_of}/{run_id}.json
      data/reports/latest.json          (pointer)
      data/reports/{as_of}.json         (latest-of-day pointer for backward compat)
      data/reports/{as_of}/_index.jsonl (append index)
    """
    root = Path(cfg.get("_root") or Path.cwd())
    folder = root / "data" / "reports"
    folder.mkdir(parents=True, exist_ok=True)
    as_of = str(payload.get("as_of") or "na")[:10]
    run_id = str(payload.get("run_id") or payload.get("production_run_id") or new_run_id())
    payload = {**payload, "run_id": run_id, "production_run_id": run_id}
    day_dir = folder / as_of
    day_dir.mkdir(parents=True, exist_ok=True)
    run_path = day_dir / f"{run_id}.json"
    if run_path.exists():
        # collision — append suffix
        run_id = f"{run_id}-{uuid4().hex[:4]}"
        payload["run_id"] = run_id
        payload["production_run_id"] = run_id
        run_path = day_dir / f"{run_id}.json"
    text = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    run_path.write_text(text, encoding="utf-8")
    # latest pointers (overwrite OK — they are pointers)
    (folder / "latest.json").write_text(text, encoding="utf-8")
    (folder / f"{as_of}.json").write_text(text, encoding="utf-8")
    idx = day_dir / "_index.jsonl"
    with idx.open("a", encoding="utf-8") as f:
        f.write(
            json.dumps(
                {
                    "run_id": run_id,
                    "as_of": as_of,
                    "path": str(run_path.relative_to(folder)),
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "n_platform_reports": len(payload.get("platform_reports") or []),
                    "final_buy": sum(
                        1 for d in (payload.get("canonical_decisions") or []) if d.get("committee_approve")
                    ),
                },
                ensure_ascii=False,
            )
            + "\n"
        )
    logger.info("[REPORT_PERSIST] as_of=%s run_id=%s path=%s", as_of, run_id, run_path)
    return run_path


def append_live_observation(cfg: dict[str, Any], obs: dict[str, Any]) -> Path:
    """Append-only live observation jsonl — never mutates Research Snapshot."""
    root = Path(cfg.get("_root") or Path.cwd())
    day = str(obs.get("research_date") or obs.get("as_of") or datetime.now().date())[:10]
    path = root / "data" / "live_observations" / f"{day}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        **obs,
        "observed_at": obs.get("observed_at") or datetime.now(timezone.utc).isoformat(),
        "observation_id": obs.get("observation_id") or f"L{uuid4().hex[:10]}",
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    return path


def record_production_run_meta(cfg: dict[str, Any], meta: dict[str, Any]) -> Path:
    root = Path(cfg.get("_root") or Path.cwd())
    path = root / "data" / "production_runs.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(meta, ensure_ascii=False, default=str) + "\n")
    return path


class PaperOrderIdempotencyStore:
    """One paper order per final_decision_id."""

    def __init__(self, cfg: dict[str, Any] | None = None) -> None:
        root = Path((cfg or {}).get("_root") or Path.cwd())
        self.path = root / "data" / "cache" / "paper_order_idempotency.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"orders": {}}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return {"orders": {}}

    def _save(self, data: dict[str, Any]) -> None:
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def get(self, final_decision_id: str) -> dict[str, Any] | None:
        return (self._load().get("orders") or {}).get(str(final_decision_id))

    def mark(self, final_decision_id: str, order_meta: dict[str, Any]) -> None:
        data = self._load()
        orders = dict(data.get("orders") or {})
        orders[str(final_decision_id)] = {
            **order_meta,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        }
        data["orders"] = orders
        self._save(data)
