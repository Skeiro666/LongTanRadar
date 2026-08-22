from __future__ import annotations

from typing import Any


def _cluster_key(event: dict[str, Any]) -> tuple[str, str]:
    return (
        str(event.get("event_type") or "OTHER"),
        str(event.get("direction") or "NEUTRAL"),
    )


def cluster_timeline_events(events: list[dict[str, Any]], *, max_clusters: int = 12) -> list[dict[str, Any]]:
    """
    Merge multiple articles/events sharing (event_type, direction) into compact clusters.
    Preserves evidence_ids for audit; drops duplicate headline bodies from LLM path.
    """
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for ev in events or []:
        if not isinstance(ev, dict):
            continue
        groups.setdefault(_cluster_key(ev), []).append(ev)

    clusters: list[dict[str, Any]] = []
    for (etype, direction), items in groups.items():
        items.sort(key=lambda x: float(x.get("impact_score") or 0), reverse=True)
        rep = items[0]
        evidence: list[str] = []
        for it in items:
            for eid in (it.get("event_id"), it.get("news_id"), it.get("evidence_id")):
                if eid and str(eid) not in evidence:
                    evidence.append(str(eid))
        clusters.append(
            {
                "cluster_id": f"{etype}:{direction}",
                "event_type": etype,
                "direction": direction,
                "n_sources": len(items),
                "impact_score": max(float(x.get("impact_score") or 0) for x in items),
                "confidence": max(float(x.get("confidence") or 0) for x in items),
                "title": rep.get("title") or rep.get("description", "")[:120],
                "event_time": rep.get("event_time"),
                "evidence_ids": evidence[:10],
                "headlines": [str(x.get("title") or "")[:120] for x in items[:5] if x.get("title")],
            }
        )

    clusters.sort(key=lambda x: float(x.get("impact_score") or 0), reverse=True)
    return clusters[:max_clusters]


from ashare.news.models import normalize_title


def compact_news_headlines(news: list[dict[str, Any]], *, max_items: int = 8) -> list[dict[str, Any]]:
    """Dedupe news rows by normalized title for LLM payloads."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in news or []:
        if not isinstance(row, dict):
            continue
        title = str(row.get("title") or row.get("headline") or "")[:120]
        key = normalize_title(title)[:48] if title else ""
        if not title or key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "title": title,
                "date": row.get("published_at") or row.get("date"),
                "classification": row.get("classification"),
                "news_id": row.get("id") or row.get("news_id"),
            }
        )
        if len(out) >= max_items:
            break
    return out
