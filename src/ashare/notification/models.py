from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

NOTIFY_LEVEL_BUY = "BUY"
NOTIFY_LEVEL_STRONG_BUY = "STRONG_BUY"
NOTIFY_LEVEL_RATING_EXIT = "RATING_EXIT"
NOTIFY_LEVEL_RISK_EXIT = "RISK_EXIT"

EXIT_NOTIFY_LEVELS = frozenset({NOTIFY_LEVEL_RATING_EXIT, NOTIFY_LEVEL_RISK_EXIT})

STATUS_PENDING = "PENDING"
STATUS_SENT = "SENT"
STATUS_FAILED = "FAILED"
STATUS_SKIPPED = "SKIPPED"
STATUS_DUPLICATE = "DUPLICATE"
STATUS_COOLDOWN = "COOLDOWN"
STATUS_DISABLED = "DISABLED"

GATE_NOTIFY = "NOTIFY"
GATE_SKIP = "SKIP"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_notification_id() -> str:
    return f"N{datetime.now(timezone.utc).strftime('%Y%m%d')}{uuid4().hex[:8].upper()}"


@dataclass
class GateInput:
    canonical: dict[str, Any]
    snapshot: dict[str, Any] | None = None
    report: dict[str, Any] | None = None
    has_paper_position: bool = False
    previous_decision: str | None = None


@dataclass
class GateResult:
    action: str  # NOTIFY | SKIP
    level: str | None = None
    reason: str = ""
    priority: float = 0.0
    channels: list[str] = field(default_factory=list)
    dedup_key: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class NotificationRecord:
    notification_id: str
    decision_id: str
    research_session_id: str
    snapshot_id: str
    symbol: str
    name: str | None
    level: str
    channel: str
    status: str
    dedup_key: str
    created_at: str
    sent_at: str | None = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
