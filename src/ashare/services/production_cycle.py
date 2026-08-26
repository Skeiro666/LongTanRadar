"""Production cycle identity, atomic slot claims, report persistence, live observations."""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

logger = logging.getLogger("ashare.production.cycle")

STATUS_SCHEDULED = "SCHEDULED"
STATUS_CLAIMED = "CLAIMED"
STATUS_RUNNING = "RUNNING"
STATUS_SUCCESS = "SUCCESS"
STATUS_FAILED = "FAILED"
STATUS_MISSED = "MISSED"

_TERMINAL = frozenset({STATUS_SUCCESS, STATUS_FAILED, STATUS_MISSED})
_file_claim_lock = threading.Lock()


def new_run_id(when: datetime | None = None) -> str:
    when = when or datetime.now(timezone.utc)
    local = when.astimezone() if when.tzinfo else when
    return f"{local.strftime('%Y%m%dT%H%M%S')}-{uuid4().hex[:8]}"


def idempotency_key(trading_date: str, cycle_type: str, scheduled_slot: str) -> str:
    return f"{trading_date}|{cycle_type}|{scheduled_slot}"


@dataclass
class ClaimResult:
    claimed: bool
    run_id: str | None
    status: str
    reason: str
    record: dict[str, Any] | None = None


class AtomicIdempotencyStore:
    """
    Atomic claim_once for scheduler slots.

    Prefer Redis SET NX; fall back to O_CREAT|O_EXCL claim files.
    Never use check-then-act (is_done → run → mark).
    """

    def __init__(self, cfg: dict[str, Any] | None = None, *, lease_sec: int = 3600) -> None:
        self.cfg = cfg or {}
        root = Path(self.cfg.get("_root") or Path.cwd())
        self.root = root
        self.dir = root / "data" / "cache" / "scheduler_claims"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.index_path = root / "data" / "cache" / "scheduler_idempotency.json"
        self.lease_sec = int(lease_sec)
        self._redis_ok: bool | None = None
        self._force_file = bool(self.cfg.get("_force_file_claims"))

    def _safe_name(self, key: str) -> str:
        return key.replace("|", "__").replace(":", "_").replace("/", "_")

    def _claim_path(self, key: str) -> Path:
        return self.dir / f"{self._safe_name(key)}.json"

    def _redis(self):
        if self._force_file:
            return None
        try:
            from ashare.db.redis_client import get_redis, ping_redis, redis_url_from_env

            url = redis_url_from_env(self.cfg)
            if self._redis_ok is None:
                self._redis_ok = ping_redis(url)
            if not self._redis_ok:
                return None
            return get_redis(url)
        except Exception:  # noqa: BLE001
            self._redis_ok = False
            return None

    def _redis_key(self, key: str) -> str:
        return f"ashare:scheduler:claim:{key}"

    def get(self, key: str) -> dict[str, Any] | None:
        path = self._claim_path(key)
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                pass
        r = self._redis()
        if r is not None:
            try:
                raw = r.get(self._redis_key(key))
                if raw:
                    return json.loads(raw)
            except Exception:  # noqa: BLE001
                pass
        return None

    def _is_reclaimable(self, rec: dict[str, Any] | None) -> bool:
        if not rec:
            return True
        st = str(rec.get("status") or "")
        if st in _TERMINAL:
            return False
        if st in {STATUS_CLAIMED, STATUS_RUNNING}:
            try:
                started = datetime.fromisoformat(str(rec.get("started_at") or rec.get("claimed_at") or ""))
                age = (datetime.now(timezone.utc) - started.astimezone(timezone.utc)).total_seconds()
                return age > self.lease_sec
            except Exception:  # noqa: BLE001
                return False
        return False

    def claim_once(
        self,
        key: str,
        *,
        run_id: str,
        meta: dict[str, Any] | None = None,
    ) -> ClaimResult:
        """Atomically claim a slot. At most one worker wins."""
        existing = self.get(key)
        if existing and not self._is_reclaimable(existing):
            return ClaimResult(
                claimed=False,
                run_id=existing.get("run_id"),
                status=str(existing.get("status") or STATUS_SUCCESS),
                reason="IDEMPOTENT",
                record=existing,
            )

        now = datetime.now(timezone.utc).isoformat()
        record = {
            "idempotency_key": key,
            "run_id": run_id,
            "status": STATUS_CLAIMED,
            "claimed_at": now,
            "started_at": now,
            "finished_at": None,
            "error": None,
            **(meta or {}),
        }

        r = self._redis()
        if r is not None:
            try:
                ok = r.set(
                    self._redis_key(key),
                    json.dumps(record, ensure_ascii=False),
                    nx=True,
                    ex=max(self.lease_sec * 48, 86400),
                )
                if not ok:
                    cur = self.get(key)
                    if cur and self._is_reclaimable(cur):
                        r.set(
                            self._redis_key(key),
                            json.dumps(record, ensure_ascii=False),
                            ex=max(self.lease_sec * 48, 86400),
                        )
                        self._write_file(key, record)
                        self._index_upsert(key, record)
                        return ClaimResult(True, run_id, STATUS_CLAIMED, "CLAIMED", record)
                    return ClaimResult(
                        False,
                        (cur or {}).get("run_id"),
                        str((cur or {}).get("status") or STATUS_CLAIMED),
                        "IDEMPOTENT",
                        cur,
                    )
                self._write_file(key, record)
                self._index_upsert(key, record)
                return ClaimResult(True, run_id, STATUS_CLAIMED, "CLAIMED", record)
            except Exception as exc:  # noqa: BLE001
                logger.warning("redis claim_once failed, falling back to file: %s", exc)

        with _file_claim_lock:
            path = self._claim_path(key)
            if path.exists():
                cur = self.get(key)
                if cur and not self._is_reclaimable(cur):
                    return ClaimResult(
                        False,
                        (cur or {}).get("run_id"),
                        str((cur or {}).get("status") or STATUS_SUCCESS),
                        "IDEMPOTENT",
                        cur,
                    )
                path.unlink(missing_ok=True)
            try:
                fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                cur = self.get(key)
                return ClaimResult(
                    False,
                    (cur or {}).get("run_id"),
                    str((cur or {}).get("status") or STATUS_CLAIMED),
                    "IDEMPOTENT",
                    cur,
                )
            try:
                os.write(fd, json.dumps(record, ensure_ascii=False, indent=2).encode("utf-8"))
            finally:
                os.close(fd)
            self._index_upsert(key, record)
            return ClaimResult(True, run_id, STATUS_CLAIMED, "CLAIMED", record)

    def update_status(
        self,
        key: str,
        *,
        status: str,
        error: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        rec = dict(self.get(key) or {})
        rec["status"] = status
        if status == STATUS_RUNNING:
            rec["started_at"] = rec.get("started_at") or datetime.now(timezone.utc).isoformat()
        if status in _TERMINAL:
            rec["finished_at"] = datetime.now(timezone.utc).isoformat()
        if error is not None:
            rec["error"] = error
        if extra:
            rec.update(extra)
        self._write_file(key, rec)
        self._index_upsert(key, rec)
        r = self._redis()
        if r is not None:
            try:
                r.set(
                    self._redis_key(key),
                    json.dumps(rec, ensure_ascii=False),
                    ex=max(self.lease_sec * 48, 86400),
                )
            except Exception:  # noqa: BLE001
                pass
        return rec

    def mark_missed(self, key: str, *, meta: dict[str, Any] | None = None) -> ClaimResult:
        """Atomically mark a slot as MISSED (no execution)."""
        run_id = f"MISSED-{uuid4().hex[:8]}"
        claim = self.claim_once(key, run_id=run_id, meta={**(meta or {})})
        if not claim.claimed:
            return claim
        rec = self.update_status(
            key,
            status=STATUS_MISSED,
            error="MARK_MISSED",
            extra={**(meta or {}), "run_id": run_id},
        )
        return ClaimResult(True, run_id, STATUS_MISSED, "MARK_MISSED", rec)

    def _write_file(self, key: str, record: dict[str, Any]) -> None:
        path = self._claim_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")

    def _index_upsert(self, key: str, record: dict[str, Any]) -> None:
        data: dict[str, Any] = {"completed": {}}
        if self.index_path.exists():
            try:
                data = json.loads(self.index_path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                data = {"completed": {}}
        completed = dict(data.get("completed") or {})
        completed[key] = {
            "run_id": record.get("run_id"),
            "status": record.get("status"),
            "completed_at": record.get("finished_at") or record.get("claimed_at"),
            "cycle_type": record.get("cycle_type"),
            "slot": record.get("scheduled_slot") or record.get("slot"),
        }
        if len(completed) > 500:
            items = sorted(completed.items(), key=lambda kv: str(kv[1].get("completed_at") or ""))
            completed = dict(items[-400:])
        data["completed"] = completed
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        self.index_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def is_done(self, key: str) -> bool:
        rec = self.get(key)
        return bool(rec and str(rec.get("status")) in _TERMINAL)

    def mark_done(self, key: str, *, run_id: str, meta: dict[str, Any] | None = None) -> None:
        self.update_status(key, status=STATUS_SUCCESS, extra={"run_id": run_id, **(meta or {})})


IdempotencyStore = AtomicIdempotencyStore


def persist_production_report(cfg: dict[str, Any], payload: dict[str, Any]) -> Path:
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
        run_id = f"{run_id}-{uuid4().hex[:4]}"
        payload["run_id"] = run_id
        payload["production_run_id"] = run_id
        run_path = day_dir / f"{run_id}.json"
    text = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    run_path.write_text(text, encoding="utf-8")
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
