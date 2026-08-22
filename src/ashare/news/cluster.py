from __future__ import annotations

from typing import Any

from ashare.news.models import normalize_title


def _cluster_key(event: dict[str, Any], *, by_symbol: bool = True) -> tuple:
    sym = str(event.get("symbol") or "") if by_symbol else ""
    etype = str(event.get("event_type") or "OTHER")
    direction = str(event.get("direction") or event.get("event_direction") or "NEUTRAL")
    # Same event across republished headlines: type + direction + symbol
    return (sym, etype, direction)


def cluster_timeline_events(
    events: list[dict[str, Any]],
    *,
    max_clusters: int = 12,
    by_symbol: bool = True,
) -> list[dict[str, Any]]:
    """
    Merge republished / multi-headline coverage into one Event + N Evidence refs.
    """
    groups: dict[tuple, list[dict[str, Any]]] = {}
    for ev in events or []:
        if not isinstance(ev, dict):
            continue
        groups.setdefault(_cluster_key(ev, by_symbol=by_symbol), []).append(ev)

    clusters: list[dict[str, Any]] = []
    for key, items in groups.items():
        sym, etype, direction = key if by_symbol else ("", key[0], key[1])
        items.sort(key=lambda x: float(x.get("impact_score") or x.get("event_impact") or 0), reverse=True)
        rep = items[0]
        evidence_ids: list[str] = []
        facts: list[str] = []
        headlines: list[str] = []
        for it in items:
            for eid in (it.get("evidence_id"), it.get("event_id"), it.get("news_id")):
                if eid and str(eid) not in evidence_ids:
                    evidence_ids.append(str(eid))
            title = str(it.get("title") or it.get("description") or "")[:200]
            if title and title not in headlines:
                headlines.append(title)
            for f in it.get("facts") or []:
                if f and f not in facts:
                    facts.append(str(f)[:300])
            if title and not facts:
                facts.append(title)

        impact = max(float(x.get("impact_score") or x.get("event_impact") or 0) for x in items)
        conf = max(float(x.get("confidence") or 0) for x in items)
        cluster_id = f"CL_{etype}_{direction}_{sym or 'NA'}"[:48]
        clusters.append(
            {
                "event_id": rep.get("event_id") or cluster_id,
                "cluster_id": cluster_id,
                "symbol": sym or rep.get("symbol"),
                "event_type": etype,
                "direction": direction,
                "impact": impact,
                "impact_score": impact,
                "confidence": conf,
                "novelty": rep.get("novelty") or rep.get("novelty_score"),
                "published_at": rep.get("event_time") or rep.get("published_at"),
                "available_at": rep.get("discovery_time") or rep.get("event_time"),
                "n_sources": len(items),
                "facts": facts[:5],
                "evidence_ids": evidence_ids[:12],
                "headlines": headlines[:6],
                "title": rep.get("title") or (headlines[0] if headlines else ""),
                "event_time": rep.get("event_time"),
                "inferences": list(rep.get("inferences") or [])[:3],
                "hypotheses": list(rep.get("hypotheses") or [])[:3],
            }
        )

    clusters.sort(key=lambda x: float(x.get("impact_score") or 0), reverse=True)
    return clusters[:max_clusters]


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
                "evidence_id": row.get("evidence_id"),
            }
        )
        if len(out) >= max_items:
            break
    return out
