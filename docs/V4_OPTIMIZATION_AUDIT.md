# V4 Optimization Audit — Phase 0 (Code-Only)

**Project:** LongTan Radar (`ashare` package)  
**Audit date:** 2026-08-22  
**Scope:** Read actual code under `src/ashare/`, `config/`, `tests/`, `web/`. README treated as non-authoritative where it diverges.  
**Phase 0 rule:** No business-code changes in this document.

---

## A. Current Complete Data Flow

### A.1 End-to-end research cycle (`run_research`)

**Entry:** `src/ashare/services/research.py` → `run_research()`  
**Triggers:** `POST /api/research/run`, Agent `run_picks()` → `run_research()`, CLI picks/research.

```
build_leader_pool(cfg)                    # pool/builder.py — full-market spot + events
  → ensure_panel(symbols)                   # data/provider.py
  → NewsOpportunityEngine.discover()        # news/opportunity.py — market flash, no LLM
  → score_candidates(rows)                # factors/score.py — factor ranks for shortlist
  → run_roundtable(cfg, shortlist)          # ai/roundtable.py — LLM on top_n (default 3)
  → CandidateEngine.build_research_universe # candidate/__init__.py — union + ranking
  → ResearchSessionEngine.run_pool()        # research/session.py — up to max_council=12
       → build_snapshot()
       → AICouncilEngine.run_parallel()    # 5 LLM calls / symbol
       → DebateEngine.run()                # 0 LLM (template)
       → ChairmanEngine.summarize()         # 1 LLM / symbol
  → ReviewEngine.attribution_report()       # research/tracking.py — no LLM
  → persist_report → data/reports/latest.json + Redis cache
```

### A.2 News pipeline (two paths)

| Path | Entry | Flow |
|------|-------|------|
| **Discovery** (News→Stock) | `NewsOpportunityEngine.discover()` | `collect_latest()` → `dedupe_news()` → `filter_asof()` → `link_entities_open()` → `classify_news()` → `extract_events()` → `annotate_event()` → rank/reject → `NewsCandidate` |
| **Per-stock** (Stock→News) | `NewsIntelligenceEngine.collect_stock()` | providers fetch → `dedupe` → `link_entities()` + **min_link_confidence 0.5** → classify → extract → score → `build_package()` |

**Key files:** `news/engine.py`, `dedup.py`, `linking.py`, `classify.py`, `extract.py`, `score.py`, `package.py`, `opportunity.py`, `hypothesis.py`.

**No semantic event clustering for LLM.** Dedup is ID/URL/title-hash; discovery dedupes `(symbol, event_type)`.

### A.3 Candidate union & ranking

**File:** `src/ashare/candidate/__init__.py` → `CandidateEngine.build_research_universe()`

```
pool candidates (limit_up/strong/profit_gap/tech_leader)
  → ProfitInflectionEngine + EventEngine enrich
  → filter quality D + low event
  → cap max_after_events (100)
  → FactorEngine.asof_rows → leader_score
  → merge news_discovery.news_candidates (tag candidate_sources)
  → weighted candidate_score (news.yaml weights)
  → sort → max_union (100) → max_research_pool (20)
  → collect_stock() on top 20 only
  → rescore with net_event_score
```

**Fields:** `candidate_score`, `leader_score`, `profit_inflection.score`, `event_score`, `news_score`, `ml_prediction`, `candidate_sources[]`.

**Gap:** `config/research.yaml` `ml_ranking.weight_in_candidate_score: 0.35` is **not wired**; active ML weight is `news.yaml` `candidate_weights.ml: 0.10`. ML runs in `run_pool()` **after** universe cut — does not re-rank union.

### A.4 ML ranking

**File:** `src/ashare/ml/ranking.py` — LightGBM excess-return ranker.  
**Use:** `ResearchSessionEngine.run_pool()` → `predict_rows()` enriches rows; council heuristics use `ml_prediction`. **Not a gate, not a re-sort of union.**

### A.5 Council / roundtable (dual AI stacks)

| Stack | When | Roles | LLM calls |
|-------|------|-------|-----------|
| **Roundtable** | Always if `ai.roundtable: true` on `shortlist` (top_n≈3) | dragon, event, risk (+rebuttal), chair | **4 / run** |
| **Platform Council** | `research.enabled: true`, up to `funnel.max_council: 12` | fundamental, quant, event, valuation, bear + chair | **6 / symbol** |

**Council payload builder:** `research/intel_package.py` → `build_research_intelligence(snapshot, role_id=...)`.  
**Role-specific filtering:** Only `news_package.role_views[role_id]` vs full package — **quant/profit/event blocks still sent to every role.**

**Debate:** `DebateEngine.run()` — deterministic templates, **0 LLM**. `debate_v1` prompt in YAML is unused for LLM.

### A.6 Paper trading

**Live path:** `services/agent.py` → `run_picks()` / `execute_picks()` → `PaperTradingBroker` → `brokers/paper.py`  
**Gate:** Roundtable `committee_verdict` / `committee_approve`; optional `ai/trade_review.py` if `ai.trade_review: true` (**default false**).  
**Fill price:** `latest_marks()` same-day close (not T+1 open).  
**Outcomes:** Paper fills **not** linked to `TrackingEngine` research outcomes.

### A.7 Outcome / attribution

**File:** `src/ashare/research/tracking.py`  
- `TrackingEngine.outcomes_for_report()` — forward returns at horizons 1/3/5/10/20/60  
- `ReviewEngine.summarize_by_source()` — buckets: `news_only`, `quant_only`, `news_plus_quant`  
- `ReviewEngine.ab_compare()` — **defined, never called in production**  
- `benchmark_returns` **never passed** from `run_research()` → `excess_return` always `None` in prod  
- `news/outcome.py` — **unwired** standalone event outcomes

---

## B. LLM Call Budget (Current)

### B.1 All LLM call sites

| # | File | Function | Trigger | Model |
|---|------|----------|---------|-------|
| 1 | `ai/client.py` | `LLMClient.chat()` | All wrappers | Per caller |
| 2 | `ai/roundtable.py` | `_ask_role()` | `run_research` shortlist | `client_for_role` (Qwen/DeepSeek per role) |
| 3 | `ai/roundtable.py` | `_ask_risk_rebuttal()` | multi_model + risk_sees_others | Kimi (default) |
| 4 | `ai/roundtable.py` | `_ask_chair()` | end of roundtable | chair model |
| 5 | `ai/roundtable.py` | `_run_single_model()` | legacy mode only | global model |
| 6 | `research/council.py` | `AICouncilEngine._call_role()` | each platform report | aliased committee models |
| 7 | `research/council.py` | `ChairmanEngine.summarize()` | each platform report | chair |
| 8 | `ai/trade_review.py` | `review_trade_candidates()` | execute_picks if no roundtable | global (off by default) |
| 9 | `ai/review.py` | `review_backtest()` | CLI/API backtest review | global |
| 10 | `ai/optimizer.py` | `propose_updates()` | **Agent every cycle** | global |
| 11 | `strategy/ai_select.py` | `AISelectStrategy._picks()` | backtest if strategy=ai_select | global + **date cache** |

**Token usage:** `client.py` lines 201–205 return `content` only — **`resp.usage` never read**. No cost ledger.

### B.2 Worst-case LLM calls per `run_research()`

| Component | Formula | Default config |
|-----------|---------|----------------|
| Roundtable | 4 | `top_n=3`, `multi_model`, `risk_sees_others=true` |
| Platform council | `min(len(research_universe), max_council) × 6` | 20 pool → **12 × 6 = 72** |
| **Total research run** | **4 + 72 = 76** | |

### B.3 Agent cycle (additional)

| Step | LLM calls |
|------|-----------|
| `run_research()` | up to **76** |
| `propose_updates()` | **+1** |
| `execute_picks()` trade_review | **0** (roundtable present; trade_review off) |
| **Agent cycle worst** | **~77** |

If user runs research manually without agent: **76**.  
Interval: `agent.interval_sec: 1800` (30 min) when autostart on.

### B.4 Average LLM calls (typical prod run)

Assumes: 12 council symbols, roundtable on 3 picks, all roles succeed (no heuristic skip):

| Metric | Estimate |
|--------|----------|
| Roundtable | 4 |
| Council | 12 × 6 = 72 |
| **Per research run** | **~76** |
| Per agent cycle | **~77** |

**Heuristic fallbacks** (unconfigured LLM / API error) reduce billed calls but **do not reduce attempted calls** when configured.

### B.5 Token estimates (no runtime metrics — character-based proxy)

Assumptions: ~2.5 chars/token Chinese+JSON mix; `max_tokens=4096` ceiling per call.

| Call type | User payload cap | Est. input tokens | Est. output tokens |
|-----------|------------------|-------------------|---------------------|
| Council role | 10,000 chars + system ~1.5k chars | **2,800–4,500** | **300–800** |
| Chairman | 12,000 chars + system ~1.2k | **3,200–5,000** | **400–1,000** |
| Roundtable role | 12,000 chars + ROLE_SYSTEM ~800 | **3,000–4,500** | **400–900** |
| Roundtable chair | 14,000 chars | **3,500–5,500** | **500–1,200** |
| Optimizer | 8,000 chars context | **2,500–3,500** | **200–600** |

**Per council symbol (6 calls):** ~**18k–25k input**, ~**2.5k–5k output**.  
**12 symbols:** ~**216k–300k input**, ~**30k–60k output** per full research run.  
**+ Roundtable (~4 calls on 3 names):** ~**12k–18k input** additional.

**Rough total per `run_research()`:** **230k–320k input tokens**, **35k–65k output tokens** (order-of-magnitude; **not measured in prod**).

### B.6 Chairman input size (current)

`ChairmanEngine.summarize()` sends JSON truncated to **12,000 chars** containing:
- `research_intelligence` subset (still includes `quant_context`, hypotheses, evidence_ids)
- Full `opinions` dict (all 5 role JSON outputs)
- `debate` list
- `snapshot_quant`

**Duplication:** Chairman receives role outputs that already consumed the same underlying snapshot; **does not re-fetch news raw text** but **does receive fat quant_context again**.

---

## C. Duplication & Waste Analysis

### C.1 Top 10 Token waste points (ranked)

| Rank | Location | Issue | Est. waste |
|------|----------|-------|------------|
| 1 | `AICouncilEngine.run_parallel()` | **5 roles × 12 symbols = 60 calls** with ~80% overlapping `research_intelligence` | **~50–65% of council tokens** |
| 2 | **Valuation role** | LLM invoked even when `value_available=false`; prompt says unavailable but call still made | **~8–10% of council calls** |
| 3 | **Dual AI stacks** | Roundtable (4 calls) + Platform Council (72) on **same research run** — two committees for overlapping names | **~5% calls + confusion** |
| 4 | `build_research_intelligence()` | Sends `news_context.last_7d` + `timeline` + `news_event_context` + hypotheses to **every** role | **~15–25% per-role input** |
| 5 | No **research cache** | Same symbol/event/factor → full re-call next cycle | **Unbounded repeat waste** |
| 6 | `roundtable.build_roundtable_payload()` | Fetches `collect_stock()` per candidate + kline + full news_package in **12k JSON** | **Roundtable input bloat** |
| 7 | **Agent optimizer** | `propose_updates()` every 30 min with full metrics JSON; can set `retrain: true` | **+1 call/cycle + train cost** |
| 8 | `ROLE_SYSTEM` / prompts | Long persona text × every roundtable role | **~500–800 tokens/call** |
| 9 | **No event clustering** | Multiple articles → multiple timeline entries → repeated facts in AI context | **News token multiplier** |
| 10 | **max_tokens=4096** default | Output ceiling far above needed JSON schema | Risk of verbose outputs |

### C.2 Top 10 research/selection quality bottlenecks

| Rank | Issue | Evidence |
|------|-------|----------|
| 1 | **ML not in union ranking** | `ml_ranking.weight_in_candidate_score` unwired; ML after top-20 cut |
| 2 | **No Research Gate** | All top-20 get `collect_stock` + top-12 get full 6-call council |
| 3 | **Fixed 5-role council** | Event/Valuation called regardless of candidate profile |
| 4 | **No AI incremental alpha metric** | `ab_compare()` unused; no quant-only vs council ranking compare |
| 5 | **No benchmark excess in prod** | `excess_return` always null in attribution |
| 6 | **Paper vs research disconnect** | Roundtable picks ≠ platform_reports universe; trading uses roundtable only |
| 7 | **Valuation data permanently unavailable** | `value_available=false`, `industry_map.available=false` — role adds noise |
| 8 | **News discovery → council gap** | Many discovery rejects (`NOT_ENOUGH_EVIDENCE`); mapping without industry graph |
| 9 | **Same-bar / live fill mismatch** | Paper fills at spot close; backtest uses T+1 — attribution hard to compare |
| 10 | **Optimizer may overfit weights** | LLM adjusts factor weights from short paper history without walk-forward guard |

### C.3 Repeated content sent to LLM

- Same `research_hypotheses`, `candidate_sources`, `data_availability` across 5 council roles.
- Same `quant_context` / `factor_context` to fundamental, event, bear roles.
- `news_event_context` (full discovery blob) attached even when role is quant-only.
- Roundtable sends **multi-symbol** payload to each role (all candidates in one JSON).
- Chairman re-embeds `quant_context` after roles already analyzed quant.

### C.4 News repetition degree

| Layer | Mechanism | Effect |
|-------|-----------|--------|
| `dedupe_news()` | source_id, URL, title hash | Raw fetch dedup ✓ |
| `extract_events()` | one event_type per article | Per-article ✓ |
| Discovery | one `(symbol, event_type)` candidate | Partial ✓ |
| **Missing** | Cross-article event cluster (20 articles → 1 order event) | **High duplication in timeline** |
| Package | up to 15 `last_7d` + 12 timeline events per stock | Sent to intel package |
| Intel | timeline[:12] + last_7d to all roles | **No compact evidence-only mode** |

### C.5 Roles receiving unnecessary data

| Role | Over-sent today |
|------|-----------------|
| quant | news last_7d, profit_context, full hypotheses |
| fundamental | full factor grid, news timeline |
| event | quant_context, factor_context |
| valuation | full package when value unavailable |
| bear | same as bull roles + duplicate news |
| chairman | quant_context + full opinions (appropriate) but also redundant snapshot fields |

### C.6 Cache opportunities (none implemented except)

| What | Status |
|------|--------|
| `AISelectStrategy` date file cache | ✓ `data/cache/ai_decisions/{date}.json` |
| Redis research latest | Final report only, not per-role LLM |
| Council role response cache | **Missing** |
| Context hash skip | **Missing** |
| Incremental role refresh | **Missing** |
| News event hash | **Missing** |

### C.7 Rule-based replacements (candidates)

| Today (LLM) | Could be rules |
|-------------|----------------|
| Valuation when `value_available=false` | Already has heuristic — **skip LLM entirely** |
| Debate | Already rule-based ✓ |
| Research Gate | **New — rules only (spec)** |
| Dynamic council role selection | **New — rules only (spec)** |
| News classify/extract | Already keyword rules ✓ |
| Optimizer weight tweaks | Could be bounded rule adjustments + less frequent LLM |

### C.8 AI calls that can be cancelled (V4 target)

- Valuation LLM when data unavailable (**immediate win**).
- Event role when no hypotheses and `net_event_score ≈ 0`.
- Quant role when factor/ML signals below threshold.
- Full council for symbols failing Research Gate.
- Roundtable **or** platform council — **not both** on same run (config flag).
- Optimizer on cycles with no new roundtable summary change.
- Re-council when `context_hash` unchanged.

### C.9 AI calls that must be retained

- **Chairman** synthesis (compressed input) for gate-pass symbols.
- **Bear** for high-score / high price-in-risk candidates.
- **Event** when high-confidence structured event + hypotheses exist.
- **Fundamental** when profit_inflection score/material.
- **Quant** when ML/factor edge is dominant source.
- News discovery **does not need LLM** today (already rule-based) ✓.

---

## D. Metrics Inventory (Current vs Required)

### D.1 Candidate Alpha

| Question | Current state |
|----------|---------------|
| Can we stat quant discovery T+5/10/20? | **Partial** — `summarize_by_source()` by tag `leader/event/profit/news` on research outcomes |
| Excess vs benchmark? | **No** in prod (`benchmark_returns` not passed) |
| Named "Candidate Alpha"? | **No** |

### D.2 News Alpha

| Question | Current state |
|----------|---------------|
| News-only bucket stats? | **Yes** — `source_bucket: news_only` in `tracking.py` |
| News discovery candidates tracked separately? | **Partial** — only if they enter council and get outcomes |
| `news/outcome.py` | **Unwired** |

### D.3 AI Incremental Alpha

| Question | Current state |
|----------|---------------|
| Compare ranking with vs without council? | **No** — `ab_compare()` exists but unwired |
| Compare roundtable buy vs factor-only? | **No** |
| **Conclusion** | **Does not exist as a metric** |

### D.4 Token Cost

| Question | Current state |
|----------|---------------|
| Per-call token logging? | **No** |
| Cost USD estimate? | **No** |
| Per-cycle / per-symbol rollup? | **No** |
| **Conclusion** | **Not computable from runtime today** (estimate from char caps only) |

---

## E. Minimal Modification Plan (Phased)

Aligned with user spec Phases 1–11. **Phase 0 = this document only.**

| Phase | Deliverable | Token savings (est.) | Quality risk |
|-------|-------------|----------------------|--------------|
| **1** Token tracking in `LLMClient.chat()` + `AICostTracker` + JSONL log | Infrastructure | 0% (measure first) | None |
| **2** `build_role_context()` — slim payloads per role | Context compression | **25–35%** input | Low if evidence_ids preserved |
| **3** Event cluster + compact evidence schema | News compression | **15–25%** on event-heavy names | Low |
| **4** `ResearchCache` + context_hash + version keys | Cache hits | **30–50%** on repeat cycles | Medium — stale cache risk |
| **5** Dynamic Council — conditional roles | Skip valuation/event/quant | **30–40%** council calls | Medium — need gate rules |
| **6** Research Gate (no LLM) | Fewer symbols enter council | **40–60%** calls (combined) | Low if top names kept |
| **7** Incremental research — partial role refresh | Delta-only chairman | **20–40%** on daily updates | Medium |
| **8** Discovery alpha by source (wire benchmark) | Metrics only | 0% | None |
| **9** AI Incremental Alpha (wire `ab_compare` + ranking diff) | Metrics only | 0% | None |
| **10** Frontend cost + alpha dashboard | UX | 0% | None |
| **11** `docs/V4_BENCHMARK.md` baseline vs V4 | Validation | — | — |

**Cumulative token target (realistic):** Phases 1–7 → **50–70%** reduction vs baseline when cache warm.  
**LLM call target:** Dynamic council + gate + skip valuation → **50%+ call reduction** (76 → ~25–35 typical).

---

## F. Answers to Required 18 Questions

### 1. Top 10 Token waste points
See **§C.1**.

### 2. Top 10 selection quality bottlenecks
See **§C.2**.

### 3. Worst LLM calls per research cycle
**~77** (76 research + 1 optimizer on agent cycle). Research alone: **76**.

### 4. Average LLM calls per research cycle
**~76** with default funnel (12 council × 6 + 4 roundtable). Lower if council pool < 12 or API failures → heuristics.

### 5. Average input size per role
Council role: **~3,000–4,500 tokens** (10k char user JSON + system). Roundtable role: **~3,000–4,500 tokens** (shared multi-symbol payload).

### 6. Chairman input size
**Up to ~5,000 tokens** (12k char cap + system + embedded opinions).

### 7. News repetition degree
Raw dedup **good**; **no cross-source event clustering**; up to **15 headlines + 12 timeline events** per stock in AI path; same facts repeated across **5 roles**.

### 8. What can be cached
Role outputs, chairman output, context_hash per (symbol, role, event_hash, factor_version, prompt_version), discovery results intraday, roundtable per (shortlist hash).

### 9. Conditional roles
**Valuation** (data unavailable), **Event** (no hypotheses/low impact), **Quant** (weak factors), **Fundamental** (weak profit signal), **Bear** (always for high-score/high-risk). Roundtable roles already specialized but always run.

### 10. News Discovery effect stats complete?
**Partial** — source bucket win-rate in `ReviewEngine`; no isolated news-discovery cohort without entering council; `event_outcome.py` unwired.

### 11. AI Incremental Alpha computable?
**No** — stub only.

### 12. Token Cost computable?
**No** — must add Phase 1 tracking.

### 13. Minimal modification scheme
Phases 1–7 incremental (see **§E**); no engine deletion; gate + dynamic council + cache + context compression.

### 14. Estimated token savings
**50–70%** after Phases 2–7; **up to 80%** with aggressive cache + gate on repeat cycles.

### 15. Estimated LLM call reduction
**50–65%** (76 → ~27–38) with dynamic council + gate; **+4** roundtable eliminable if merged with platform path.

### 16. Expected research quality impact
**Neutral to slight positive** if bear/chairman kept for top names; **risk** if gate too aggressive drops serendipitous news names.

### 17. Risks
Stale cache; gate false negatives; over-compressed context drops evidence; dual-stack removal changes UX; optimizer/auto-retrain cost spikes; no benchmark → false confidence in alpha stats.

### 18. Phase 1–11 plan
See **§E** table — matches user spec order.

---

## G. Key File Index (for implementers)

| Area | Paths |
|------|-------|
| LLM transport | `src/ashare/ai/client.py` |
| Roundtable | `src/ashare/ai/roundtable.py` |
| Council | `src/ashare/research/council.py`, `session.py` |
| Intel payload | `src/ashare/research/intel_package.py` |
| Snapshot versions | `src/ashare/research/snapshot.py` |
| Research orchestration | `src/ashare/services/research.py` |
| Candidate union | `src/ashare/candidate/__init__.py` |
| News | `src/ashare/news/*.py` |
| Tracking | `src/ashare/research/tracking.py` |
| Agent | `src/ashare/services/agent.py`, `ai/optimizer.py` |
| Paper trade | `src/ashare/services/trading.py`, `brokers/paper.py` |
| Config | `config/default.yaml`, `research.yaml`, `news.yaml`, `prompts.yaml` |
| Tests | `tests/test_attribution.py`, `test_phase10_research_cycle.py`, `test_news_discovery_v3_checklist.py` |

---

## H. README vs Code Conflicts (noted)

| README claim | Code reality |
|--------------|--------------|
| ML weight in candidate score from research.yaml | **Uses `news.yaml` `candidate_weights.ml: 0.10`** |
| Single committee path | **Two paths:** roundtable + platform council both run |
| Token/cost visibility | **Not implemented** |
| `ab_test` in research.yaml | **Unwired** |

---

## I. Phase 0 Exit Criteria

- [x] Full data flow documented from code
- [x] LLM call sites enumerated
- [x] Token waste and quality bottlenecks ranked
- [x] Metrics gap analysis (Candidate/News/AI Incremental/Token Cost)
- [x] Minimal phased plan with savings estimates
- [x] **No business code modified**

**Next step:** User confirmation → **Phase 1: Token Tracking** (`LLMClient` usage capture + `AICostTracker` + tests).
