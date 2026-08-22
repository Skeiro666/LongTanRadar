from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any

from ashare.config_loaders import load_yaml_config
from ashare.notification.models import (
    GATE_NOTIFY,
    GATE_SKIP,
    NOTIFY_LEVEL_BUY,
    NOTIFY_LEVEL_RISK_EXIT,
    NOTIFY_LEVEL_STRONG_BUY,
    GateInput,
    GateResult,
)
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
            level = NOTIFY_LEVEL_RISK_EXIT
            dedup = build_dedup_key(symbol=sym, decision_id=decision_id, level=level, event_id=_event_id(inp.snapshot, inp.report))
            ch = list((self.n_cfg.get("channels") or {}).get("risk_exit") or ["wechat", "email"])
            return GateResult(
                action=GATE_NOTIFY,
                level=level,
                reason="risk_exit_blocked",
                priority=1.0,
                channels=ch,
                dedup_key=dedup,
                metadata={
                    "previous_decision": inp.previous_decision,
                    "current_decision": rating,
                    "change_reason": "risk_filter_blocked",
                    "expected_excess_return": eer,
                    "confidence": confidence,
                    "data_quality": dq,
                    "risk_quality": rq,
                },
            )

        if rating in {"WATCH", "PASS", "GATE_SKIP", "SKIP"}:
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


def rank_and_cap(candidates: list[tuple[GateInput, GateResult]], max_n: int) -> list[tuple[GateInput, GateResult]]:
    notify = [(inp, gr) for inp, gr in candidates if gr.action == GATE_NOTIFY]
    notify.sort(key=lambda x: x[1].priority, reverse=True)
    return notify[:max_n]
