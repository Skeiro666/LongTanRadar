from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ashare.news.models import RawNews, make_id, title_hash, utc_now
from ashare.symbols import to_symbol


def unix_to_iso(v: Any) -> str:
    try:
        n = int(float(str(v).strip()))
        if n > 10_000_000_000:
            n = n / 1000
        return datetime.fromtimestamp(n, tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return str(v or "")


def row_to_news(
    *,
    source: str,
    title: str,
    symbol: str = "",
    name: str = "",
    url: str = "",
    summary: str = "",
    published_at: str = "",
    media: str = "",
    source_id: str = "",
) -> RawNews | None:
    title = (title or "").strip()
    if not title:
        return None
    return RawNews(
        id=make_id("N"),
        source=source,
        source_id=str(source_id or ""),
        url=url or "",
        title=title,
        content=summary,
        summary=(summary or "")[:400],
        published_at=published_at,
        fetched_at=utc_now().isoformat(),
        media=media,
        title_hash=title_hash(title),
        query_symbol=to_symbol(symbol) if symbol else "",
        query_name=name or "",
    )
