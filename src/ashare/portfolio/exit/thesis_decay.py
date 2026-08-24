from __future__ import annotations

"""Thesis decay — BUY thesis vs current state. Does not change exit_score."""

from typing import Any


ACTIVE_STATES = {"ACTIVE", "DEVELOPING", "CONFIRMED"}
DONE_STATES = {"COMPLETED", "INVALIDATED"}


def evaluate_thesis_decay(
    *,
    buy_thesis: dict[str, Any] | None,
    current: dict[str, Any] | None,
) -> dict[str, Any]:
    buy = buy_thesis or {}
    cur = current or {}
    components: list[dict[str, Any]] = []

    def _cmp(key: str, buy_val: Any, cur_val: Any, kind: str = "state") -> None:
        if buy_val is None and cur_val is None:
            components.append({"key": key, "available": False, "decay": None})
            return
        decay = 0.0
        if kind == "state":
            b = str(buy_val or "UNKNOWN").upper()
            c = str(cur_val or "UNKNOWN").upper()
            if b in ACTIVE_STATES and c in DONE_STATES:
                decay = 0.9
            elif b in ACTIVE_STATES and c == "UNKNOWN":
                decay = 0.3
            elif c in {"WEAKENING", "WEAK", "NEGATIVE", "NEUTRAL"} and b in {"STRONG", "POSITIVE", "ACTIVE"}:
                decay = 0.7
        elif kind == "direction":
            b = str(buy_val or "").lower()
            c = str(cur_val or "").lower()
            if ("pos" in b or "bull" in b) and ("neg" in c or "bear" in c or c == "neutral"):
                decay = 0.85 if "neg" in c or "bear" in c else 0.5
        elif kind == "strength":
            try:
                bv, cv = float(buy_val), float(cur_val)
                if bv > 0 and cv < bv * 0.5:
                    decay = 0.7
                elif cv < 0 < bv:
                    decay = 0.8
            except (TypeError, ValueError):
                components.append({"key": key, "available": False, "decay": None})
                return
        components.append({"key": key, "available": True, "buy": buy_val, "current": cur_val, "decay": round(decay, 4)})

    _cmp("profit", buy.get("profit_state"), cur.get("profit_state"), "state")
    _cmp("event", buy.get("event_state"), cur.get("event_state"), "state")
    _cmp("news", buy.get("news_direction"), cur.get("news_direction"), "direction")
    _cmp("momentum", buy.get("momentum"), cur.get("momentum"), "strength")
    _cmp("leader", buy.get("leader_score"), cur.get("leader_score"), "strength")

    avail = [c for c in components if c.get("available") and c.get("decay") is not None]
    if not avail:
        return {
            "available": False,
            "thesis_decay": None,
            "level": "UNKNOWN",
            "components": components,
            "note": "insufficient_thesis_fields",
        }
    score = sum(float(c["decay"]) for c in avail) / len(avail)
    if score >= 0.65:
        level = "HIGH"
    elif score >= 0.35:
        level = "MEDIUM"
    else:
        level = "LOW"
    return {
        "available": True,
        "thesis_decay": round(score, 4),
        "level": level,
        "components": components,
        "buy_thesis": buy,
        "current_thesis": cur,
    }
