from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class MarketEvent:
    event_type: str
    event_time: str
    source: str
    direction: float  # -1..+1
    impact_score: float  # -1..+1
    confidence: float
    time_horizon: str = "near"
    affected_business: str = ""
    description: str = ""
    symbol: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# Rule priors — AI may refine later; not sole decision maker.
EVENT_PRIORS: dict[str, float] = {
    "业绩预增": 0.7,
    "业绩预减": -0.7,
    "重大订单": 0.7,
    "新产品": 0.5,
    "产品涨价": 0.55,
    "并购": 0.4,
    "重组": 0.35,
    "产能投产": 0.45,
    "海外订单": 0.6,
    "政策利好": 0.8,
    "行业反转": 0.5,
    "重大合同": 0.65,
    "股权激励": 0.35,
    "回购": 0.4,
    "大股东增持": 0.45,
    "减持": -0.5,
    "监管处罚": -0.9,
    "诉讼": -0.6,
    "商誉风险": -0.7,
    "业绩暴雷": -0.95,
    "涨停": 0.4,
    "强势": 0.3,
    "技术龙头": 0.25,
}


class EventEngine:
    def __init__(self, cfg: dict[str, Any] | None = None) -> None:
        self.cfg = cfg or {}
        self.priors = dict(EVENT_PRIORS)

    def from_pool_row(self, row: dict[str, Any]) -> list[MarketEvent]:
        sym = str(row.get("symbol") or "")
        events: list[MarketEvent] = []
        tags = list(row.get("event_tags") or [])
        sources = list(row.get("sources") or [])
        if row.get("source") and row["source"] not in sources:
            sources.append(row["source"])
        ftype = str(row.get("forecast_type") or "")
        if ftype:
            tags.append(ftype)
        for src in sources:
            if src == "limit_up":
                tags.append("涨停")
            elif src == "strong":
                tags.append("强势")
            elif src == "tech_leader":
                tags.append("技术龙头")
            elif src in {"profit_gap", "yjyg"}:
                tags.append("业绩预增" if float(row.get("profit_gap_score") or 0) >= 0 else "业绩预减")

        seen: set[str] = set()
        for tag in tags:
            t = str(tag)
            key = t
            for name in self.priors:
                if name in t:
                    key = name
                    break
            if key in seen:
                continue
            seen.add(key)
            impact = float(self.priors.get(key, 0.1))
            events.append(
                MarketEvent(
                    event_type=key,
                    event_time=str(row.get("as_of") or row.get("date") or ""),
                    source=",".join(sources) or "pool",
                    direction=1.0 if impact >= 0 else -1.0,
                    impact_score=impact,
                    confidence=0.55,
                    description=t,
                    symbol=sym,
                )
            )
        return events

    def score(self, events: list[MarketEvent]) -> float:
        if not events:
            return 0.0
        # confidence-weighted average, clipped
        num = sum(e.impact_score * e.confidence for e in events)
        den = sum(e.confidence for e in events) or 1.0
        return float(max(-1.0, min(1.0, num / den)))

    def enrich_candidates(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out = []
        for r in rows:
            evs = self.from_pool_row(r)
            score = self.score(evs)
            item = dict(r)
            item["events"] = [e.to_dict() for e in evs]
            # No detected events → valid ZERO (not UNAVAILABLE). Engine failure sets status elsewhere.
            item["event"] = {
                "score": score,
                "events": item["events"],
                "available": True,
                "status": "ZERO" if abs(score) < 1e-15 else "VALID",
            }
            item["event_score"] = score
            item["event_status"] = "ZERO" if abs(score) < 1e-15 else "VALID"
            item["event_score_available"] = True
            out.append(item)
        return out
