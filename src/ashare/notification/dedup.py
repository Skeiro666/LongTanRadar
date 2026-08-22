from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from ashare.config_loaders import load_yaml_config
from ashare.notification.models import (
    NOTIFY_LEVEL_BUY,
    NOTIFY_LEVEL_RISK_EXIT,
    NOTIFY_LEVEL_STRONG_BUY,
    STATUS_COOLDOWN,
    STATUS_DUPLICATE,
    GateResult,
)


def _cfg(cfg: dict[str, Any] | None) -> dict[str, Any]:
    return load_yaml_config(cfg, "notification")


def _parse_ts(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None


_UPGRADE_PATHS = {
    ("WATCH", NOTIFY_LEVEL_BUY),
    ("PASS", NOTIFY_LEVEL_BUY),
    ("WATCH", NOTIFY_LEVEL_STRONG_BUY),
    ("BUY", NOTIFY_LEVEL_STRONG_BUY),
    (NOTIFY_LEVEL_BUY, NOTIFY_LEVEL_RISK_EXIT),
    (NOTIFY_LEVEL_STRONG_BUY, NOTIFY_LEVEL_RISK_EXIT),
}


class DedupStore:
    """In-memory + persisted dedup/cooldown checks."""

    def __init__(self, history: list[dict[str, Any]], cfg: dict[str, Any] | None = None) -> None:
        self.history = history
        self.cfg = cfg or {}
        self.n_cfg = _cfg(self.cfg)
        self.cooldown_cfg = dict(self.n_cfg.get("cooldown") or {})

    def check(
        self,
        *,
        dedup_key: str,
        symbol: str,
        level: str,
        event_id: str | None,
        previous_decision: str | None,
        current_decision: str,
    ) -> tuple[bool, str]:
        """Return (allowed, reason). False → block with DUPLICATE or COOLDOWN."""
        if not self.n_cfg.get("dedup", {}).get("enabled", True):
            return True, "dedup_disabled"

        now = datetime.now(timezone.utc)
        sym_hours = float(self.cooldown_cfg.get("same_symbol_hours", 24))
        evt_hours = float(self.cooldown_cfg.get("same_event_hours", 72))
        allow_upgrade = bool(self.cooldown_cfg.get("allow_upgrade", True))

        sent = [h for h in self.history if h.get("status") == "SENT"]
        for h in sent:
            if h.get("dedup_key") == dedup_key:
                return False, STATUS_DUPLICATE

        prev = (previous_decision or "").upper()
        cur = (current_decision or level or "").upper()
        is_upgrade = allow_upgrade and (prev, cur) in _UPGRADE_PATHS or (prev, level) in _UPGRADE_PATHS

        for h in sent:
            if h.get("symbol") != symbol:
                continue
            ts = _parse_ts(h.get("sent_at") or h.get("created_at"))
            if not ts:
                continue
            if now - ts < timedelta(hours=sym_hours):
                old_level = str(h.get("level") or "")
                if is_upgrade and _level_rank(level) > _level_rank(old_level):
                    continue
                if h.get("level") == level:
                    return False, STATUS_COOLDOWN

        if event_id:
            for h in sent:
                meta = h.get("metadata") or {}
                if meta.get("event_id") == event_id:
                    ts = _parse_ts(h.get("sent_at") or h.get("created_at"))
                    if ts and now - ts < timedelta(hours=evt_hours):
                        if not is_upgrade:
                            return False, STATUS_COOLDOWN

        return True, "ok"


def _level_rank(level: str) -> int:
    return {NOTIFY_LEVEL_BUY: 1, NOTIFY_LEVEL_STRONG_BUY: 2, NOTIFY_LEVEL_RISK_EXIT: 3}.get(level, 0)


def apply_dedup(
    gate_result: GateResult,
    store: DedupStore,
    *,
    symbol: str,
    event_id: str | None,
    previous_decision: str | None,
    current_decision: str,
) -> GateResult:
    if gate_result.action != "NOTIFY":
        return gate_result
    ok, reason = store.check(
        dedup_key=gate_result.dedup_key,
        symbol=symbol,
        level=gate_result.level or "",
        event_id=event_id,
        previous_decision=previous_decision,
        current_decision=current_decision,
    )
    if ok:
        return gate_result
    from ashare.notification.models import GATE_SKIP

    gr = GateResult(
        action=GATE_SKIP,
        level=gate_result.level,
        reason=reason,
        priority=gate_result.priority,
        dedup_key=gate_result.dedup_key,
        metadata={**gate_result.metadata, "blocked_by": reason},
    )
    return gr
