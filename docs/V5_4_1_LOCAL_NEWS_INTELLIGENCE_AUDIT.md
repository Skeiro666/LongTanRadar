# V5.4.1 Local News Intelligence Audit

Date: 2026-08-24  
Baseline commit: `7317d2270b1c5be92eb539762790b96eb01ba4d5`  
Scope: read-only audit of current `ashare/news/` pipeline and directly related wiring.  

This document is an audit only. It does **not** propose rewriting the news system, and it must preserve the already completed work:

1. `NEWS_AI_*` separated from Cloud Council
2. local/Ollama provider wiring
3. local entity-mapping fallback
4. rating-exit notification work

Code is authoritative. If old docs conflict with code, trust code.

## 1. Executive Summary

The repo already has a meaningful two-track news system:

- `NewsIntelligenceEngine.collect_stock()` handles **existing candidate evidence** for a known symbol.
- `NewsOpportunityEngine.discover()` handles **market-wide discovery** from latest headlines.

The local model is now wired as a **news-specific LLM client** via `NEWS_AI_*`, but its current production role is still narrow:

- it is only used in discovery
- only when rule-based entity linking fails
- only for `beneficiaries` inference
- and all LLM-inferred entities are intentionally capped low-confidence and rejected from direct positive discovery

So the current state is:

`Local LLM = Entity Mapping Fallback`

not yet:

`Local LLM = News Intelligence Engine`

That means the repo already has the right skeleton for discovery/evidence/hypothesis, but the local model is not yet used to produce structured intelligence such as `event_type`, `importance`, `novelty`, `market_relevance`, `impact_horizon`, or `summary`.

## 2. Current End-to-End Architecture

### 2.1 Stock Evidence Path

Known-symbol news evidence is handled by `src/ashare/news/engine.py`.

Current flow:

1. provider fetch by symbol
2. `filter_asof()` to prevent future leakage
3. `dedupe_news()`
4. `link_entities()` against the queried symbol only
5. weak links dropped by `min_link_confidence`
6. `classify_news()`
7. `extract_events()`
8. `annotate_event()`
9. `expectation_gap()`
10. `net_event_score()`
11. `build_package()`

This path is explicitly described in code as:

> fetch -> store -> dedup -> link -> classify -> extract -> score

and is currently **independent of LLM**.

### 2.2 Market Discovery Path

Open-market discovery is handled by `src/ashare/news/opportunity.py`.

Current flow:

1. `collect_latest()` from latest-news providers
2. `dedupe_news()`
3. `classify_news()`
4. `link_entities_open()` using code/name/alias rules
5. if no entity and `discovery.llm_mapping=true`, call local LLM fallback
6. `extract_events()`
7. `annotate_event()`
8. `EvidenceRegistry.register()`
9. `ResearchHypothesisEngine.from_event()`
10. create `NewsCandidate`
11. reject low-confidence LLM-inferred mappings
12. persist `data/news/discovery_latest.json`

This path already supports:

- discovery
- evidence ids
- hypothesis generation
- candidate union input

but local LLM is used only at the entity inference step.

## 3. Current Local LLM Wiring

### 3.1 What was already completed

The current commit already correctly separates:

- Cloud Council: `AI_*`
- Local News LLM: `NEWS_AI_*`

Relevant files:

- `src/ashare/config.py`
- `src/ashare/ai/client.py`
- `config/news.yaml`
- `src/ashare/news/llm_mapping.py`

### 3.2 How it is invoked today

`src/ashare/news/llm_mapping.py` defines a JSON-only entity mapping prompt and returns `beneficiaries`.

Actual call conditions in `src/ashare/news/opportunity.py`:

- only in `discover()`
- only if `disc["llm_mapping"]` is enabled
- only if `link_entities_open()` finds no entity
- only through `client_for_news()`

So the local model is **not** currently used for:

- event extraction
- novelty estimation
- importance estimation
- market relevance
- impact horizon
- evidence summarization
- hypothesis extraction

## 4. Existing Capabilities by Module

### 4.1 `models.py`

`src/ashare/news/models.py` already provides the main data structures:

- `RawNews`
- `NewsEntity`
- `ExtractedEvent`
- `NewsCandidate`

Important existing fields:

- `NewsEntity`: `entity_type`, `symbol`, `name`, `confidence`, `link_source`, `mapping_method`
- `ExtractedEvent`: `event_type`, `direction`, `impact_score`, `confidence`, `time_horizon`, `facts`, `inferences`, `evidence_id`
- `NewsCandidate`: `candidate_sources`, `news_score`, `relevance_score`, `novelty`, `source_quality`, `price_in_risk`, `research_hypotheses`, `investment_hypothesis`, `mapping_method`, `status`, `reject_reason`

Important gap:

- there is no first-class `entity_source` enum matching the new requested taxonomy
- there is no first-class `news_role`
- there is no structured intelligence payload model for local LLM output
- there is no explicit `possible_beneficiaries` / `hypothesis` schema in models

### 4.2 `linking.py`

`src/ashare/news/linking.py` already supports two linking modes:

- `link_entities_open()` for discovery
- `link_entities()` for known-symbol evidence

Current entity source semantics in practice:

- `code`
- `official_name`
- `alias`
- `title+code`
- `title_name`
- `title_code`
- `body_only`
- `query_weak`
- `llm_inference`

Important gap versus requested taxonomy:

Requested target:

- `explicit_code`
- `explicit_company`
- `alias`
- `fuzzy`
- `llm_inferred`
- `unknown`

Current code does not normalize to that schema yet.

### 4.3 `extract.py`

`src/ashare/news/extract.py` is keyword-based only.

It maps keywords to:

- event type
- direction score
- impact
- horizon

Current event labels include values such as:

- `EARNINGS_GUIDANCE`
- `ORDER`
- `PRICE_INCREASE`
- `CAPACITY_EXPANSION`
- `M_AND_A`
- `RESTRUCTURE`
- `SHARE_BUYBACK`
- `INSIDER_SELL`
- `INSIDER_BUY`
- `REGULATORY`
- `LITIGATION`
- `POLICY_SUPPORT`
- fallback `OTHER`

Important gaps:

- event taxonomy does not yet match the newer requested V5.4.1 taxonomy
- direction labels are currently `VERY_BULLISH/BULLISH/BEARISH/...`, not `positive/negative/neutral/mixed/unknown`
- no structured LLM news understanding step exists here
- no novelty or market-relevance extraction exists here

### 4.4 `score.py`

`src/ashare/news/score.py` currently handles:

- source quality (`A/B/C/D`)
- freshness
- relevance
- priority
- aggregate net event score

This is already useful and should be preserved.

Important gap:

- no `news_intelligence_score` composed from `importance`, `novelty`, `market_relevance`, `event_confidence`, `entity_confidence`, `source_quality`
- current score is still rule/event centric, not intelligence-schema centric

### 4.5 `package.py`

`src/ashare/news/package.py` already provides:

- `filter_asof()` with strict no-future leakage
- time buckets
- event clustering
- compact timeline
- conflict warning strings
- role views for downstream research payloads

Important existing strength:

- it already acts like a packaging layer between raw news/event output and research/Council consumption

Important gap:

- no explicit `news_role` field with `discovery/evidence/both/none`
- no structured local-intelligence result included in package payload
- current conflict output is human-readable warnings, not a numeric `news_conflict` / `conflict_score`

### 4.6 `llm_mapping.py`

`src/ashare/news/llm_mapping.py` is the entire current local-LLM news module.

It currently does only one job:

- infer possible A-share beneficiaries when no rule entity is found

Important existing constraints:

- JSON-only
- max confidence 0.45
- no non-A-share output
- fallback-safe

Important gap:

- entity resolution and news intelligence are not split
- no separate intelligence extraction prompt
- no cache
- no prompt version
- no per-news result persistence

## 5. Discovery, Evidence, and Hypothesis State

The repo already has the beginnings of the target funnel:

- **Discovery**: yes
- **Evidence**: yes
- **Hypothesis**: yes

But each is only partially implemented.

### 5.1 Discovery

Direct discovery already exists through `NewsOpportunityEngine.discover()`.

Current behavior:

- rule-linked companies can become `NewsCandidate`
- LLM-inferred entities are rejected with `LOW_CONFIDENCE`

This already enforces a key policy you want to keep:

- inferred entities do not directly become BUY

### 5.2 Evidence

Evidence already exists for known candidates via `collect_stock()`.

Current behavior:

- only keep headlines that really match the symbol/name
- body-only noise is filtered
- news becomes structured package input for later research

Important gap:

- even if a candidate has strong supporting or contradicting news, there is no explicit `news_role=evidence`
- there is no explicit `evidence_direction=positive/negative/...`

### 5.3 Hypothesis

Hypothesis already exists through `ResearchHypothesisEngine` integration in discovery.

Current behavior:

- event-derived research hypotheses are attached to `NewsCandidate`
- but they are template/rule-derived, not local-LLM-derived structured hypotheses

Important gap:

- no dedicated hypothesis JSON schema like:
  - `hypothesis`
  - `beneficiary_industries`
  - `confidence`

## 6. Current Safety and Behavioral Constraints

These behaviors are already encoded in code/tests and must be preserved:

1. News does not directly become trade action.
2. `NewsCandidate` is discovery only, not BUY/order.
3. `filter_asof()` drops future news and even unparseable timestamps when `as_of` is set.
4. weak or inferred mapping is intentionally demoted.
5. policy/industry items without mapping become unavailable/rejected rather than fabricated stock picks.
6. provider failure degrades softly instead of crashing the research path.

These constraints are validated by current tests such as:

- `tests/test_news_intelligence.py`
- `tests/test_news_discovery.py`

## 7. What Is Already Close to the Target

The current codebase already has several pieces that should be extended rather than replaced:

- dedicated local-news client separation
- discovery vs known-symbol evidence split
- event packaging layer
- evidence ids and registry
- candidate hypothesis attachment
- low-confidence inferred-entity policy
- no-future-news filtering
- cost tracking through generic `LLMClient.chat(...)`

This is important: V5.4.1 does **not** need a blank-slate design.

## 8. Main Gaps Relative to V5.4.1 Goal

To move from:

`Local LLM = Entity Mapping Fallback`

to:

`Local LLM = News Intelligence Engine`

the main missing capabilities are:

### 8.1 Entity Resolution and Intelligence Are Coupled

Today, the only local-LLM task is entity inference.

Missing separation:

- Task A: entity resolution
- Task B: news intelligence extraction

### 8.2 Known-Entity News Does Not Trigger Local Intelligence

Today, if rule linking succeeds, the local model is not used.

But your target requires:

- explicit company news may still deserve local intelligence extraction
- local LLM should understand high-value news even when entity resolution is already solved

### 8.3 No Structured News Intelligence JSON

Missing schema for:

- `event_type`
- `direction`
- `importance`
- `novelty`
- `market_relevance`
- `impact_horizon`
- `event_confidence`
- `summary`
- `evidence`

### 8.4 No First-Class Discovery Grading

Current discovery distinguishes rule-linked vs LLM-inferred implicitly.

Missing explicit states:

- direct discovery
- inferred discovery
- hypothesis/watchlist only

### 8.5 No First-Class `entity_source`

Current values are implementation-specific string labels.

Missing normalized categories:

- `explicit_code`
- `explicit_company`
- `alias`
- `fuzzy`
- `llm_inferred`
- `unknown`

### 8.6 No First-Class `news_role`

Missing:

- `discovery`
- `evidence`
- `both`
- `none`

### 8.7 No Local-News Cache Layer

There is currently:

- raw news persistence
- evidence registry

but no cache keyed by:

- `news_id`
- `content_hash`
- `model`
- `prompt_version`

and no stored local-LLM result object/status.

### 8.8 No Local-News Version Stamp

Current system versions:

- `news_version`
- `event_engine_version`
- `provider_version`

Missing local-news-intelligence metadata:

- `model_name`
- `prompt_version`
- cached result status

### 8.9 No Explicit Performance Guardrail Layer for Local News Intelligence

Current fetch path is synchronous and mostly sequential.

Missing explicit controls for local LLM stage:

- bounded concurrency
- retry policy
- cache hit policy
- timeout policy
- token accounting per item or batch

### 8.10 No Numeric `news_conflict`

Current packaging can emit conflict warnings in text form.

Missing:

- `news_conflict`
- `conflict_score` in `0~1`

for later routing integration.

## 9. Files Most Likely to Matter in the Next Phase

If/when V5.4.1 implementation starts, the primary touch points are likely:

- `src/ashare/news/models.py`
- `src/ashare/news/linking.py`
- `src/ashare/news/llm_mapping.py`
- `src/ashare/news/extract.py`
- `src/ashare/news/score.py`
- `src/ashare/news/package.py`
- `src/ashare/news/opportunity.py`
- `src/ashare/news/engine.py`
- `src/ashare/config.py`
- `config/news.yaml`
- `src/ashare/ai/client.py`

Likely integration surfaces:

- `src/ashare/research/intel_package.py`
- `src/ashare/research/hypothesis.py`
- `src/ashare/research/price_reaction.py`
- `src/ashare/services/research.py`
- `src/ashare/candidate/__init__.py`
- `src/ashare/api/app.py`

Likely persistence/test surfaces:

- `src/ashare/news/store.py`
- `src/ashare/news/evidence_registry.py`
- `tests/test_news_intelligence.py`
- `tests/test_news_discovery.py`

## 10. Audit Conclusion

Current baseline is healthy enough for extension:

- the repo already separates local news AI from Cloud Council
- discovery/evidence/hypothesis lanes already exist
- inferred entities are already blocked from direct positive candidate promotion
- no-future leakage protections are already present

The real V5.4.1 gap is not missing infrastructure. The gap is that the local model still does only one narrow thing:

- infer a stock when rules fail

The next phase should therefore extend the existing pipeline so that local LLM becomes a **structured news-understanding layer**, while preserving:

- no BUY/SELL output
- no direct trading authority
- no Council/Risk coupling
- no fabricated entity certainty
- no future leakage

In short:

- **Current**: local LLM helps map news to stocks.
- **Target**: local LLM helps understand news, while entity resolution remains a separate task.
