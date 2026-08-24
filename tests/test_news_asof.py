from __future__ import annotations

from datetime import datetime, timezone

from ashare.news.models import RawNews, make_id, title_hash
from ashare.news.package import filter_asof


def _news(title: str, published_at: str) -> RawNews:
    return RawNews(
        id=make_id("N"),
        source="sina",
        title=title,
        fetched_at="2026-08-20T10:00:00+00:00",
        summary=title,
        published_at=published_at,
        title_hash=title_hash(title),
    )


def test_future_news_dropped():
    past = _news("旧闻", "2026-08-19 09:00:00")
    future = _news("未来", "2026-08-25 09:00:00")
    as_of = datetime(2026, 8, 20, 23, 59, tzinfo=timezone.utc)
    kept = filter_asof([past, future], as_of)
    assert len(kept) == 1
    assert kept[0].title == "旧闻"


def test_published_at_must_be_before_signal():
    """Outcome audit: news published_at <= signal_time is enforced at fetch layer."""
    as_of = datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc)
    same_day = _news("当日", "2026-08-20 11:00:00")
    after = _news("晚于信号", "2026-08-20 13:00:00")
    kept = filter_asof([same_day, after], as_of)
    assert len(kept) == 1
    assert kept[0].title == "当日"
