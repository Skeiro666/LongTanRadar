from __future__ import annotations

from datetime import datetime, timezone

from ashare.news.models import ExtractedEvent, RawNews


_MAJOR = ("新华", "中证", "证券时报", "上证", "人民日报", "央视", "第一财经", "新浪财经")
_OFFICIAL = ("公告", "交易所", "上交所", "深交所", "证监会")
_AGG = ("eastmoney", "baidu", "ths", "sina")


def source_quality(news: RawNews) -> str:
    media = (news.media or "") + (news.title or "")
    if any(k in media for k in _OFFICIAL):
        return "A"
    if any(k in media for k in _MAJOR):
        return "B"
    if news.source in _AGG:
        return "C"
    return "D"


def freshness_score(published_at: str, *, now: datetime | None = None) -> float:
    now = now or datetime.now(timezone.utc)
    ts = _parse_dt(published_at)
    if ts is None:
        return 0.4
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    hours = max(0.0, (now - ts).total_seconds() / 3600.0)
    if hours <= 24:
        return 1.0
    if hours <= 72:
        return 0.8
    if hours <= 168:
        return 0.55
    if hours <= 720:
        return 0.3
    return 0.1


def _parse_dt(s: str) -> datetime | None:
    if not s:
        return None
    s = s.strip().replace("/", "-")
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt
    except ValueError:
        pass
    if s.isdigit() and len(s) >= 10:
        try:
            n = int(s)
            if n > 10_000_000_000:
                n = int(n / 1000)
            return datetime.fromtimestamp(n, tz=timezone.utc)
        except (ValueError, OSError):
            pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(s[:19] if len(s) >= 19 else s[:10], fmt)
        except ValueError:
            continue
    return None


def relevance_score(*, link_confidence: float, classification: str, quality: str) -> float:
    qmap = {"A": 0.98, "B": 0.85, "C": 0.65, "D": 0.4}
    base = qmap.get(quality, 0.5)
    cat_boost = 0.1 if classification in {"FINANCIAL", "ORDER", "REGULATORY", "POLICY"} else 0.0
    return float(max(0.0, min(1.0, 0.55 * link_confidence + 0.35 * base + cat_boost)))


def news_priority(relevance: float, freshness: float, impact: float, quality: str) -> float:
    q = {"A": 1.0, "B": 0.85, "C": 0.65, "D": 0.4}.get(quality, 0.5)
    return float(max(0.0, min(1.0, 0.4 * relevance + 0.25 * freshness + 0.25 * impact + 0.1 * q)))


def annotate_event(ev: ExtractedEvent, news: RawNews, *, link_confidence: float, classification: str) -> ExtractedEvent:
    q = source_quality(news)
    rel = relevance_score(link_confidence=link_confidence, classification=classification, quality=q)
    fr = freshness_score(news.published_at)
    ev.source_quality = q
    ev.relevance = rel
    ev.freshness = fr
    ev.news_priority = news_priority(rel, fr, ev.impact_score, q)
    ev.confidence = min(ev.confidence, 0.3 + 0.7 * link_confidence)
    return ev


def net_event_score(events: list[ExtractedEvent], *, min_relevance: float = 0.5) -> float:
    """Do not average bull+bear blindly: weight by |direction| * impact * relevance."""
    used = [e for e in events if e.relevance >= min_relevance and e.event_type != "OTHER"]
    if not used:
        used = events
    if not used:
        return 0.0
    num = sum(e.direction_score * e.impact_score * max(e.relevance, 0.2) for e in used)
    den = sum(e.impact_score * max(e.relevance, 0.2) for e in used) or 1.0
    return float(max(-1.0, min(1.0, num / den)))
