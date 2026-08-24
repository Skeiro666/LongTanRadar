from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any

from ashare.config_loaders import load_yaml_config
from ashare.notification.models import (
    EXIT_NOTIFY_LEVELS,
    GATE_NOTIFY,
    GATE_SKIP,
    NOTIFY_LEVEL_BUY,
    NOTIFY_LEVEL_RATING_EXIT,
    NOTIFY_LEVEL_RISK_EXIT,
    NOTIFY_LEVEL_STRONG_BUY,
    GateInput,
    GateResult,
)

_BUY_RATINGS = {NOTIFY_LEVEL_BUY, NOTIFY_LEVEL_STRONG_BUY}
_RATING_EXIT_PRIORITY = {"SELL": 1.0, "PASS": 0.85, "WATCH": 0.65}
from ashare.symbols import to_symbol


def _cfg(cfg: dict[str, Any] | None) -> dict[str, Any]:
    return load_yaml_config(cfg, "notification")


def _parse_confidence(raw: Any) -> float | None:
    if raw is None:
        return None
    try:
        v = float(raw)
        if v > 1.0:
            v = v / 100.0
        return max(0.0, min(1.0, v))
    except (TypeError, ValueError):
        return None


def _expected_excess_return(snapshot: dict[str, Any] | None, report: dict[str, Any] | None) -> dict[str, Any]:
    if snapshot:
        meta = dict(snapshot.get("candidate_score_meta") or {})
        eer = dict(meta.get("expected_excess_return") or {})
        if eer.get("available") and eer.get("value") is not None:
            return eer
    hyps = list((report or {}).get("research_hypotheses") or [])
    for h in hyps:
        if not isinstance(h, dict):
            continue
        inv = dict(h.get("investment_hypothesis") or {})
        eer = dict(inv.get("expected_excess_return") or {})
        if eer.get("available") and eer.get("value") is not None:
            return eer
    return {"available": False, "value": None, "confidence": 0.0}


def _data_quality(snapshot: dict[str, Any] | None, report: dict[str, Any] | None) -> float | None:
    if not snapshot and not report:
        return None
    snap = snapshot or {}
    score = 0.0
    n = 0
    if snap.get("value_available"):
        score += 1.0
        n += 1
    news = snap.get("news_package") or (report or {}).get("news_package") or {}
    if news.get("news_ids"):
        score += 1.0
        n += 1
    if snap.get("research_hypotheses") or (report or {}).get("research_hypotheses"):
        score += 0.5
        n += 1
    council = snap.get("council") or (report or {}).get("council") or {}
    roles = [k for k in council if not str(k).startswith("_")]
    if roles:
        score += min(1.0, len(roles) / 5.0)
        n += 1
    if n == 0:
        return None
    return round(score / n, 4)


def _risk_quality(risk_status: str) -> float | None:
    rs = (risk_status or "").lower()
    if rs == "pass":
        return 1.0
    if rs == "blocked":
        return 0.0
    return None


def compute_priority(
    *,
    expected_excess: dict[str, Any],
    confidence: float | None,
    data_quality: float | None,
    risk_quality: float | None,
) -> float | None:
    if not expected_excess.get("available") or expected_excess.get("value") is None:
        return None
    if confidence is None or data_quality is None or risk_quality is None:
        return None
    eer = abs(float(expected_excess["value"]))
    return round(eer * confidence * data_quality * risk_quality, 6)


def build_dedup_key(
    *,
    symbol: str,
    decision_id: str,
    level: str,
    event_id: str | None = None,
) -> str:
    parts = [to_symbol(symbol), decision_id or "", level, event_id or ""]
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def _event_id(snapshot: dict[str, Any] | None, report: dict[str, Any] | None) -> str | None:
    snap = snapshot or {}
    ev = snap.get("event") or (report or {}).get("event") or {}
    events = list(ev.get("events") or [])
    if events and isinstance(events[0], dict):
        return str(events[0].get("event_id") or events[0].get("id") or "")
    ids = (snap.get("news_snapshot") or {}).get("event_ids") or []
    if ids:
        return str(ids[0])
    return None


class NotificationGate:
    """Evaluate NOTIFY/SKIP from canonical + risk + snapshot only. Zero LLM."""

    def __init__(self, cfg: dict[str, Any] | None = None) -> None:
        self.cfg = cfg or {}
        self.n_cfg = _cfg(self.cfg)
        self.gate_cfg = dict(self.n_cfg.get("gate") or {})

    def evaluate(self, inp: GateInput) -> GateResult:
        if not self.n_cfg.get("enabled", True):
            return GateResult(action=GATE_SKIP, reason="notification_disabled")

        canonical = inp.canonical
        rating = str(canonical.get("research_rating") or "").upper()
        risk_status = str(canonical.get("risk_status") or "").lower()
        sym = to_symbol(canonical.get("symbol") or "")
        decision_id = str(canonical.get("research_session_id") or canonical.get("research_id") or "")

        eer = _expected_excess_return(inp.snapshot, inp.report)
        confidence = _parse_confidence(canonical.get("confidence"))
        dq = _data_quality(inp.snapshot, inp.report)
        rq = _risk_quality(risk_status)

        # RISK_EXIT: held position + risk blocked
        risk_exit_cfg = dict(self.gate_cfg.get("risk_exit") or {})
        if (
            inp.has_paper_position
            and risk_status == "blocked"
            and risk_exit_cfg.get("require_risk_blocked", True)
        ):
            return self._exit_result(
                inp,
                level=NOTIFY_LEVEL_RISK_EXIT,
                sym=sym,
                decision_id=decision_id,
                rating=rating,
                reason="risk_exit_blocked",
                change_reason="risk_filter_blocked",
                priority=1.0,
                channel_key="risk_exit",
                eer=eer,
                confidence=confidence,
                dq=dq,
                rq=rq,
            )

        rating_exit = self._eval_rating_exit(inp, rating, sym, decision_id, eer, confidence, dq, rq)
        if rating_exit is not None:
            return rating_exit

        if rating in {"WATCH", "PASS", "GATE_SKIP", "SKIP", "SELL"}:
            return GateResult(action=GATE_SKIP, reason=f"rating_{rating.lower()}")

        buy_cfg = dict(self.gate_cfg.get("buy") or {})
        sb_cfg = dict(self.gate_cfg.get("strong_buy") or {})

        if rating == NOTIFY_LEVEL_STRONG_BUY:
            return self._eval_buy_level(
                inp, sb_cfg, NOTIFY_LEVEL_STRONG_BUY, sym, decision_id, eer, confidence, dq, rq, risk_status
            )
        if rating == NOTIFY_LEVEL_BUY:
            return self._eval_buy_level(
                inp, buy_cfg, NOTIFY_LEVEL_BUY, sym, decision_id, eer, confidence, dq, rq, risk_status
            )

        return GateResult(action=GATE_SKIP, reason=f"unsupported_rating_{rating}")

    def _eval_buy_level(
        self,
        inp: GateInput,
        level_cfg: dict[str, Any],
        level: str,
        sym: str,
        decision_id: str,
        eer: dict[str, Any],
        confidence: float | None,
        dq: float | None,
        rq: float | None,
        risk_status: str,
    ) -> GateResult:
        if level_cfg.get("require_risk_pass", True) and risk_status != "pass":
            return GateResult(action=GATE_SKIP, reason=f"risk_{risk_status}")

        min_conf = float(level_cfg.get("min_confidence", 0.65 if level == NOTIFY_LEVEL_BUY else 0.75))
        min_eer = float(level_cfg.get("min_expected_excess_return", 0.03 if level == NOTIFY_LEVEL_BUY else 0.05))

        if confidence is None:
            return GateResult(action=GATE_SKIP, reason="confidence_unavailable")
        if confidence < min_conf:
            return GateResult(action=GATE_SKIP, reason=f"confidence_below_{min_conf}")

        if not eer.get("available") or eer.get("value") is None:
            return GateResult(action=GATE_SKIP, reason="expected_excess_return_unavailable")
        eer_val = float(eer["value"])
        if eer_val < min_eer:
            return GateResult(action=GATE_SKIP, reason=f"eer_below_{min_eer}")

        priority = compute_priority(expected_excess=eer, confidence=confidence, data_quality=dq, risk_quality=rq)
        if priority is None:
            return GateResult(action=GATE_SKIP, reason="priority_unavailable")

        dedup = build_dedup_key(
            symbol=sym, decision_id=decision_id, level=level, event_id=_event_id(inp.snapshot, inp.report)
        )
        ch_key = "strong_buy" if level == NOTIFY_LEVEL_STRONG_BUY else "buy"
        ch = list((self.n_cfg.get("channels") or {}).get(ch_key) or (["wechat", "email"] if level == NOTIFY_LEVEL_STRONG_BUY else ["wechat"]))

        return GateResult(
            action=GATE_NOTIFY,
            level=level,
            reason="threshold_met",
            priority=priority,
            channels=ch,
            dedup_key=dedup,
            metadata={
                "previous_decision": inp.previous_decision,
                "current_decision": level,
                "change_reason": "rating_threshold",
                "expected_excess_return": eer,
                "confidence": confidence,
                "data_quality": dq,
                "risk_quality": rq,
                "eer_value": eer_val,
            },
        )

    def _eval_rating_exit(
        self,
        inp: GateInput,
        rating: str,
        sym: str,
        decision_id: str,
        eer: dict[str, Any],
        confidence: float | None,
        dq: float | None,
        rq: float | None,
    ) -> GateResult | None:
        cfg = dict(self.gate_cfg.get("rating_exit") or {})
        if not cfg.get("require_paper_position", True) or not inp.has_paper_position:
            return None

        notify_ratings = {str(r).upper() for r in (cfg.get("notify_ratings") or ["PASS", "SELL"])}
        include_watch = bool(cfg.get("include_watch_on_downgrade", True))
        prev = (inp.previous_decision or "").upper()

        should_exit = False
        change_reason = "rating_exit"
        if rating in notify_ratings:
            should_exit = True
            change_reason = "explicit_sell" if rating == "SELL" else "rating_downgrade"
        elif rating == "WATCH" and include_watch and prev in _BUY_RATINGS:
            should_exit = True
            change_reason = "rating_downgrade"

        if not should_exit:
            return None

        priority = float(_RATING_EXIT_PRIORITY.get(rating, 0.7))
        if prev in _BUY_RATINGS:
            priority = min(1.0, priority + 0.1)
        if confidence is not None:
            priority = round(priority * (0.5 + 0.5 * float(confidence)), 6)

        return self._exit_result(
            inp,
            level=NOTIFY_LEVEL_RATING_EXIT,
            sym=sym,
            decision_id=decision_id,
            rating=rating,
            reason="rating_exit",
            change_reason=change_reason,
            priority=priority,
            channel_key="rating_exit",
            eer=eer,
            confidence=confidence,
            dq=dq,
            rq=rq,
        )

    def _exit_result(
        self,
        inp: GateInput,
        *,
        level: str,
        sym: str,
        decision_id: str,
        rating: str,
        reason: str,
        change_reason: str,
        priority: float,
        channel_key: str,
        eer: dict[str, Any],
        confidence: float | None,
        dq: float | None,
        rq: float | None,
    ) -> GateResult:
        dedup = build_dedup_key(
            symbol=sym,
            decision_id=decision_id,
            level=level,
            event_id=_event_id(inp.snapshot, inp.report),
        )
        ch = list((self.n_cfg.get("channels") or {}).get(channel_key) or ["wechat", "email"])
        return GateResult(
            action=GATE_NOTIFY,
            level=level,
            reason=reason,
            priority=priority,
            channels=ch,
            dedup_key=dedup,
            metadata={
                "previous_decision": inp.previous_decision,
                "current_decision": rating,
                "change_reason": change_reason,
                "expected_excess_return": eer,
                "confidence": confidence,
                "data_quality": dq,
                "risk_quality": rq,
                "has_paper_position": inp.has_paper_position,
            },
        )


def rank_and_cap(
    candidates: list[tuple[GateInput, GateResult]],
    max_buy: int,
    max_exit: int | None = None,
) -> list[tuple[GateInput, GateResult]]:
    """Reserve separate caps for exit vs entry notifications."""
    max_exit = max_exit if max_exit is not None else max_buy
    notify = [(inp, gr) for inp, gr in candidates if gr.action == GATE_NOTIFY]
    exits = [(inp, gr) for inp, gr in notify if gr.level in EXIT_NOTIFY_LEVELS]
    entries = [(inp, gr) for inp, gr in notify if gr.level not in EXIT_NOTIFY_LEVELS]
    exits.sort(key=lambda x: x[1].priority, reverse=True)
    entries.sort(key=lambda x: x[1].priority, reverse=True)
    return exits[:max_exit] + entries[:max_buy]
