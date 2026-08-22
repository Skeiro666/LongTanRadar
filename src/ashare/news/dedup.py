from __future__ import annotations

from ashare.news.models import RawNews, normalize_title


def dedupe_news(items: list[RawNews]) -> list[RawNews]:
    """First-stage: source_id, URL, normalized title hash. No embeddings."""
    seen_sid: set[str] = set()
    seen_url: set[str] = set()
    seen_title: set[str] = set()
    out: list[RawNews] = []
    for n in items:
        sid = (n.source_id or "").strip()
        if sid and sid in seen_sid:
            continue
        url = (n.url or "").strip().split("?")[0]
        if url and url in seen_url:
            continue
        th = n.title_hash or normalize_title(n.title)
        if th and th in seen_title:
            continue
        if sid:
            seen_sid.add(sid)
        if url:
            seen_url.add(url)
        if th:
            seen_title.add(th)
        out.append(n)
    return out
