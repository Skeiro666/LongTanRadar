from __future__ import annotations

from ashare.news.entity_resolve import resolve_entities_open, entities_from_llm_guesses
from ashare.news.linking import LLM_INFERENCE_MAX_CONF
from ashare.news.schema import normalize_entity_source

from news_intel_fakes import sample_news


def test_explicit_code_and_company():
    n = sample_news("北新建材000786获得重大订单")
    ents = resolve_entities_open(n, name_map={"000786.SZ": "北新建材"})
    srcs = {e.entity_source for e in ents}
    assert srcs & {"explicit_code", "explicit_company"}
    assert normalize_entity_source("code") == "explicit_code"
    assert normalize_entity_source("official_name") == "explicit_company"
    assert normalize_entity_source("alias") == "alias"


def test_alias_and_fuzzy_and_unknown():
    n = sample_news("茅台公告回购股份")
    ents = resolve_entities_open(n, name_map={}, aliases={"茅台": "600519.SH"})
    assert ents[0].entity_source == "alias"
    assert normalize_entity_source("body_only") == "fuzzy"
    assert normalize_entity_source("query_weak") == "fuzzy"
    assert normalize_entity_source("") == "unknown"


def test_llm_inferred_source_capped():
    n = sample_news("某材料价格大幅上涨")
    ents = entities_from_llm_guesses(n, [{"symbol": "000786.SZ", "name": "北新建材", "confidence": 0.99}])
    assert ents[0].entity_source == "llm_inferred"
    assert ents[0].confidence <= LLM_INFERENCE_MAX_CONF
