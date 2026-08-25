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

# Focus monitoring tiers (orthogonal to lifecycle)
FOCUS_TIER_WATCH = "WATCH"
FOCUS_TIER_CORE = "CORE"
FOCUS_TIER_BUY_CANDIDATE = "BUY_CANDIDATE"
FOCUS_TIER_BUY_READY = "BUY_READY"


def focus_tier(row: dict[str, Any], cfg: dict[str, Any] | None = None) -> str:
    """Classify focus monitoring intensity."""
    ta = str(row.get("trade_timing_action") or "").upper()
    lc = str(row.get("lifecycle") or "").upper()
    st = str(row.get("stage") or "").upper()
    chase = float(row.get("chase_score") or 0)
    re = float(row.get("reentry_score") or 0)
    board = int(row.get("board_count") or row.get("consecutive_limit_up") or 0)
    if ta == BUY_READY or lc == BUY_READY:
        return FOCUS_TIER_BUY_READY
    # BUY_CANDIDATE tier only when timing says so and board>=2 (1板≠买点候选)
    if board >= 2 and (ta == BUY_CANDIDATE or lc == BUY_CANDIDATE):
        return FOCUS_TIER_BUY_CANDIDATE
    if board >= 2 and re >= 0.55 and ta != "PASS":
        return FOCUS_TIER_BUY_CANDIDATE
    if st == "EXTREME" and chase >= 0.55:
        return FOCUS_TIER_WATCH
    if lc in {FOCUS, LEADER_CONFIRMED} or (board >= 2 and re >= 0.35):
        return FOCUS_TIER_CORE
    return FOCUS_TIER_WATCH


def board_lifecycle_hint(board: int, leader_score: float, cfg: dict[str, Any] | None = None) -> str:
    """Board-based lifecycle hint — leader_score still required for confirmation."""
    lc_cfg = dict((cfg or {}).get("lifecycle") or {})
    b1 = int(lc_cfg.get("board_potential") or 1)
    b2 = int(lc_cfg.get("board_candidate") or 2)
    b3 = int(lc_cfg.get("board_confirmed") or 3)
    b4 = int(lc_cfg.get("board_core") or 4)
    min_ls = float(((cfg or {}).get("focus") or {}).get("min_leader_score") or 0.35)
    if board >= b4 and leader_score >= min_ls:
        return LEADER_CONFIRMED  # CORE_LEADER candidate → confirmed focus path
    if board >= b3 and leader_score >= min_ls * 0.85:
        return LEADER_CONFIRMED
    if board >= b2:
        return LEADER_CANDIDATE
    if board >= b1:
        return NEW_LIMIT_UP
    return NEW_LIMIT_UP


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
