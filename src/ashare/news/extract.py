from __future__ import annotations

from ashare.news.models import ExtractedEvent, RawNews, make_id

# keyword -> (event_type, direction_score, impact, horizon)
_EXTRACT: list[tuple[tuple[str, ...], str, float, float, str]] = [
    (("预增", "业绩大增", "净利润增长"), "EARNINGS_GUIDANCE", 0.7, 0.65, "SHORT_TERM"),
    (("预减", "首亏", "业绩暴雷"), "EARNINGS_GUIDANCE", -0.8, 0.8, "SHORT_TERM"),
    (("订单", "重大合同", "中标"), "ORDER", 0.7, 0.7, "MEDIUM_TERM"),
    (("涨价", "提价"), "PRICE_INCREASE", 0.55, 0.5, "MEDIUM_TERM"),
    (("扩产", "投产", "产能"), "CAPACITY_EXPANSION", 0.45, 0.45, "MEDIUM_TERM"),
    (("并购", "收购"), "M_AND_A", 0.4, 0.5, "MEDIUM_TERM"),
    (("重组",), "RESTRUCTURE", 0.35, 0.45, "MEDIUM_TERM"),
    (("回购",), "SHARE_BUYBACK", 0.4, 0.35, "SHORT_TERM"),
    (("减持",), "INSIDER_SELL", -0.5, 0.55, "SHORT_TERM"),
    (("增持",), "INSIDER_BUY", 0.45, 0.45, "SHORT_TERM"),
    (("立案", "处罚"), "REGULATORY", -0.9, 0.9, "SHORT_TERM"),
    (("诉讼",), "LITIGATION", -0.6, 0.55, "MEDIUM_TERM"),
    (("政策", "补贴"), "POLICY_SUPPORT", 0.6, 0.55, "MEDIUM_TERM"),
]


def _direction_label(score: float) -> str:
    if score >= 0.75:
        return "VERY_BULLISH"
    if score >= 0.2:
        return "BULLISH"
    if score <= -0.75:
        return "VERY_BEARISH"
    if score <= -0.2:
        return "BEARISH"
    return "NEUTRAL"


def extract_events(news: RawNews, *, symbol: str, relevance: float) -> list[ExtractedEvent]:
    text = f"{news.title} {news.summary}"
    hits: list[ExtractedEvent] = []
    seen: set[str] = set()
    now = news.fetched_at
    for keys, etype, dscore, impact, horizon in _EXTRACT:
        if not any(k in text for k in keys):
            continue
        if etype in seen:
            continue
        seen.add(etype)
        eid = make_id("E")
        hits.append(
            ExtractedEvent(
                event_id=eid,
                news_id=news.id,
                symbol=symbol,
                event_type=etype,
                title=news.title,
                description=news.summary[:240],
                event_time=news.published_at or now,
                discovery_time=now,
                source=news.source,
                source_url=news.url,
                direction=_direction_label(dscore),
                direction_score=float(dscore),
                impact_score=float(impact),
                confidence=min(0.85, 0.4 + relevance * 0.5),
                time_horizon=horizon,
                facts=[news.title],
                inferences=[],
                evidence_id=news.id,
            )
        )
    if not hits:
        hits.append(
            ExtractedEvent(
                event_id=make_id("E"),
                news_id=news.id,
                symbol=symbol,
                event_type="OTHER",
                title=news.title,
                description=news.summary[:240],
                event_time=news.published_at or now,
                discovery_time=now,
                source=news.source,
                source_url=news.url,
                direction="NEUTRAL",
                direction_score=0.0,
                impact_score=0.15,
                confidence=0.35,
                time_horizon="SHORT_TERM",
                facts=[news.title],
                inferences=[],
                evidence_id=news.id,
            )
        )
    return hits
