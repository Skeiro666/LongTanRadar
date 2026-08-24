from __future__ import annotations

from ashare.news.linking import link_entities, link_entities_open, llm_inference_entities
from ashare.news.models import NewsEntity, RawNews
from ashare.news.schema import discovery_grade, normalize_entity_source


def annotate_entity_source(ent: NewsEntity) -> NewsEntity:
    src = normalize_entity_source(ent.mapping_method or ent.link_source)
    ent.entity_source = src
    return ent


def resolve_entities_open(
    news: RawNews,
    *,
    name_map: dict[str, str] | None = None,
    aliases: dict[str, str] | None = None,
) -> list[NewsEntity]:
    ents = link_entities_open(news, name_map=name_map, aliases=aliases)
    return [annotate_entity_source(e) for e in ents]


def resolve_entities_stock(news: RawNews, *, symbol: str, name: str = "") -> list[NewsEntity]:
    ents = link_entities(news, symbol=symbol, name=name)
    return [annotate_entity_source(e) for e in ents]


def entities_from_llm_guesses(news: RawNews, guesses: list[dict]) -> list[NewsEntity]:
    ents = llm_inference_entities(news, guesses)
    return [annotate_entity_source(e) for e in ents]


def entity_payload(ent: NewsEntity) -> dict:
    src = getattr(ent, "entity_source", "") or normalize_entity_source(ent.mapping_method or ent.link_source)
    return {
        "symbol": ent.symbol,
        "company_name": ent.name,
        "entity_confidence": float(ent.confidence),
        "entity_source": src,
        "discovery_grade": discovery_grade(src),
        "mapping_method": ent.mapping_method or ent.link_source,
    }
