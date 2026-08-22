from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from ashare.news.models import ExtractedEvent, RawNews
from ashare.news.score import _parse_dt


_ROLE_CATS = {
    "fundamental": {"FINANCIAL", "ORDER", "CAPACITY", "PRODUCT", "COMPANY", "M_AND_A"},
    "quant": {"MARKET", "FINANCIAL", "ORDER"},
    "event": None,  # all
    "valuation": {"FINANCIAL", "DIVIDEND", "M_AND_A"},
    "bear": {"REGULATORY", "LITIGATION", "INSIDER_SELL", "FINANCIAL"},
}


def _age_hours(news: RawNews, now: datetime) -> float | None:
    ts = _parse_dt(news.published_at)
    if ts is None:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return (now - ts).total_seconds() / 3600.0


def filter_asof(items: list[RawNews], as_of: datetime | None) -> list[RawNews]:
    """Drop news published after as_of (no future leakage into research)."""
    if as_of is None:
        return items
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=timezone.utc)
    out = []
    for n in items:
        ts = _parse_dt(n.published_at)
        if ts is None:
            # Unparseable timestamp cannot be proven <= as_of — drop (no leakage).
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if ts <= as_of:
            out.append(n)
    return out


def build_package(
    *,
    symbol: str,
    name: str,
    news: list[RawNews],
    events: list[ExtractedEvent],
    classifications: dict[str, str],
    entities: list[dict[str, Any]],
    net_score: float,
    provider_status: str,
    incomplete: bool,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    buckets = {"last_24h": [], "last_3d": [], "last_7d": [], "last_30d": []}
    for n in news:
        d = n.to_dict()
        d["classification"] = classifications.get(n.id, "OTHER")
        d["ai_used"] = True
        hours = _age_hours(n, now)
        if hours is None or hours <= 720:
            buckets["last_30d"].append(d)
        if hours is not None and hours <= 24:
            buckets["last_24h"].append(d)
        if hours is not None and hours <= 72:
            buckets["last_3d"].append(d)
        if hours is None or hours <= 168:
            buckets["last_7d"].append(d)

    timeline = sorted(
        [e.to_dict() for e in events if e.event_type != "OTHER" or e.impact_score >= 0.3],
        key=lambda x: x.get("event_time") or "",
        reverse=True,
    )
    conflicts = []
    dirs = {e.direction for e in events if e.event_type != "OTHER"}
    if "BULLISH" in dirs or "VERY_BULLISH" in dirs:
        if "BEARISH" in dirs or "VERY_BEARISH" in dirs:
            conflicts.append("同时存在利好与利空事件，禁止简单相加")

    exp = {
        "available": False,
        "gap": None,
        "note": "无一致预期数据，禁止假装知道市场预期",
    }

    def role_view(role: str) -> dict[str, Any]:
        cats = _ROLE_CATS.get(role)
        evs = [e.to_dict() for e in events]
        if cats:
            evs = [e for e in evs if e.get("event_type") in cats or classifications.get(e.get("news_id") or "", "") in cats]
            nlist = [x for x in buckets["last_7d"] if x.get("classification") in cats]
        else:
            nlist = buckets["last_7d"]
        return {"news": nlist[:12], "events": evs[:12]}

    return {
        "symbol": symbol,
        "name": name,
        "news_data_incomplete": incomplete,
        "provider_status": provider_status,
        "counts": {
            "last_24h": len(buckets["last_24h"]),
            "last_7d": len(buckets["last_7d"]),
            "last_30d": len(buckets["last_30d"]),
        },
        "last_24h": buckets["last_24h"][:8],
        "last_7d": buckets["last_7d"][:15],
        "last_30d": buckets["last_30d"][:40],
        "events": [e.to_dict() for e in events],
        "timeline": timeline[:30],
        "conflicts": conflicts,
        "net_event_score": net_score,
        "expectation": exp,
        "entities": entities,
        "role_views": {r: role_view(r) for r in ("fundamental", "quant", "event", "valuation", "bear")},
        "legacy_headlines": [
            {"date": n.published_at, "title": n.title, "summary": n.summary[:180], "media": n.media}
            for n in news[:5]
        ],
        "news_ids": [n.id for n in news],
        "event_ids": [e.event_id for e in events],
    }
