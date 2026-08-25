from __future__ import annotations

from enum import StrEnum
from typing import Any

NEW_LIMIT_UP = "NEW_LIMIT_UP"
LEADER_CANDIDATE = "LEADER_CANDIDATE"
LEADER_CONFIRMED = "LEADER_CONFIRMED"
FOCUS = "FOCUS"
BUY_CANDIDATE = "BUY_CANDIDATE"
BUY_READY = "BUY_READY"
HOLDING = "HOLDING"
EXIT_WATCH = "EXIT_WATCH"
EXIT = "EXIT"
DROPPED = "DROPPED"
WAIT = "WAIT"


class LifecycleState(StrEnum):
    NEW_LIMIT_UP = NEW_LIMIT_UP
    LEADER_CANDIDATE = LEADER_CANDIDATE
    LEADER_CONFIRMED = LEADER_CONFIRMED
    FOCUS = FOCUS
    BUY_CANDIDATE = BUY_CANDIDATE
    BUY_READY = BUY_READY
    HOLDING = HOLDING
    EXIT_WATCH = EXIT_WATCH
    EXIT = EXIT
    DROPPED = DROPPED
    WAIT = WAIT


FOCUS_STATES = frozenset({FOCUS, BUY_CANDIDATE, BUY_READY, HOLDING, EXIT_WATCH})
COUNCIL_FULL_STATES = frozenset({FOCUS, BUY_CANDIDATE, BUY_READY})
ACTIVE_STATES = frozenset(
    {
        NEW_LIMIT_UP,
        LEADER_CANDIDATE,
        LEADER_CONFIRMED,
        FOCUS,
        BUY_CANDIDATE,
        BUY_READY,
        HOLDING,
        EXIT_WATCH,
        WAIT,
    }
)


def council_tier(lifecycle: str, cfg: dict[str, Any] | None = None) -> str:
    lc = str(lifecycle or NEW_LIMIT_UP).upper()
    full = set((cfg or {}).get("council", {}).get("full_tiers") or list(COUNCIL_FULL_STATES))
    if lc in full:
        return "full"
    if lc == DROPPED:
        return "none"
    return "scan"


def news_tier(lifecycle: str, timing_action: str, cfg: dict[str, Any] | None = None) -> str:
    lc = str(lifecycle or "").upper()
    ta = str(timing_action or "").upper()
    tiers = dict((cfg or {}).get("news_tiers") or {})
    if ta == BUY_READY or lc == BUY_READY:
        return str(tiers.get("buy_candidate") or "local_llm_full_plus_refresh")
    if lc in {FOCUS, BUY_CANDIDATE}:
        return str(tiers.get("focus") or "local_llm_full")
    if lc in {LEADER_CANDIDATE, LEADER_CONFIRMED}:
        return str(tiers.get("leader_candidate") or "local_llm_light")
    return str(tiers.get("scan") or "rules_only")
