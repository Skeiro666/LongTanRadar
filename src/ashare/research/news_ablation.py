from __future__ import annotations

from typing import Any, Callable

from ashare.research.news_alpha import _aggregate
from ashare.research.signal_attribution import discovery_primary


def build_news_ablation(
    outcomes: list[dict[str, Any]],
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Offline experiment arms — statistics only, no weight changes."""

    def no_news(o: dict[str, Any]) -> bool:
        srcs = {str(s).lower() for s in (o.get("candidate_sources") or [])}
        return "news" not in srcs

    def evidence_only(o: dict[str, Any]) -> bool:
        sec = {str(s).lower() for s in (o.get("secondary_sources") or [])}
        return "news" in sec and discovery_primary(o) != "news"

    def discovery_only(o: dict[str, Any]) -> bool:
        return discovery_primary(o) == "news"

    def both(o: dict[str, Any]) -> bool:
        srcs = {str(s).lower() for s in (o.get("candidate_sources") or [])}
        return "news" in srcs and bool(srcs & {"quant", "event", "profit"})

    def with_council(o: dict[str, Any]) -> bool:
        routing = o.get("ai_routing") or {}
        return "news" in {str(s).lower() for s in (o.get("candidate_sources") or [])} and str(
            routing.get("routing_level") or ""
        ).upper() not in {"", "LOW"}

    arms: dict[str, Callable[[dict[str, Any]], bool]] = {
        "no_news": no_news,
        "evidence_only": evidence_only,
        "discovery_only": discovery_only,
        "discovery_and_evidence": both,
        "news_plus_council": with_council,
    }
    return {
        "available": bool(outcomes),
        "arms": {name: _aggregate(outcomes, filter_fn=fn, cfg=cfg) for name, fn in arms.items()},
        "note": "Statistics only — candidate weights unchanged.",
    }
