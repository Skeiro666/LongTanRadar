from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ashare.notification.models import NotificationRecord, _now_iso, new_notification_id


class NotificationStore:
    def __init__(self, cfg: dict[str, Any] | None = None) -> None:
        self.cfg = cfg or {}
        root = Path(self.cfg.get("_root") or Path(__file__).resolve().parents[3])
        self.dir = root / "data" / "notifications"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.log_path = self.dir / "notifications.jsonl"
        self.outcome_path = self.dir / "outcomes.jsonl"

    def _read_all(self) -> list[dict[str, Any]]:
        if not self.log_path.exists():
            return []
        rows = []
        for line in self.log_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return rows

    def list_recent(self, limit: int = 200) -> list[dict[str, Any]]:
        return list(reversed(self._read_all()[-limit:]))

    def append(self, record: NotificationRecord | dict[str, Any]) -> dict[str, Any]:
        row = record.to_dict() if isinstance(record, NotificationRecord) else dict(record)
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
        return row

    def update_status(
        self,
        notification_id: str,
        *,
        status: str,
        sent_at: str | None = None,
        error: str | None = None,
    ) -> None:
        rows = self._read_all()
        updated = []
        for row in rows:
            if row.get("notification_id") == notification_id:
                row = {**row, "status": status}
                if sent_at:
                    row["sent_at"] = sent_at
                if error is not None:
                    row["error"] = error
            updated.append(row)
        self.log_path.write_text(
            "\n".join(json.dumps(r, ensure_ascii=False, default=str) for r in updated) + ("\n" if updated else ""),
            encoding="utf-8",
        )

    def append_outcome(self, outcome: dict[str, Any]) -> None:
        with self.outcome_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(outcome, ensure_ascii=False, default=str) + "\n")

    def list_outcomes(self, limit: int = 500) -> list[dict[str, Any]]:
        if not self.outcome_path.exists():
            return []
        rows = []
        for line in self.outcome_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        return rows[-limit:]

    def last_sent_for_symbol(self, symbol: str) -> dict[str, Any] | None:
        for row in reversed(self._read_all()):
            if row.get("symbol") == symbol and row.get("status") == "SENT":
                return row
        return None

    def make_record(
        self,
        *,
        canonical: dict[str, Any],
        level: str,
        channel: str,
        status: str,
        dedup_key: str,
        metadata: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> NotificationRecord:
        return NotificationRecord(
            notification_id=new_notification_id(),
            decision_id=str(canonical.get("research_session_id") or canonical.get("research_id") or ""),
            research_session_id=str(canonical.get("research_session_id") or canonical.get("research_id") or ""),
            snapshot_id=str(canonical.get("snapshot_id") or canonical.get("research_session_id") or ""),
            symbol=str(canonical.get("symbol") or ""),
            name=canonical.get("name"),
            level=level,
            channel=channel,
            status=status,
            dedup_key=dedup_key,
            created_at=_now_iso(),
            sent_at=_now_iso() if status == "SENT" else None,
            error=error,
            metadata=metadata or {},
        )
