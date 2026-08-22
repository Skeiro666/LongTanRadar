# V5 Phase 0 Audit — Alpha & Cost Loop (Code-Only)

**Project:** LongTan Radar (`ashare`)  
**Repo:** https://github.com/Skeiro666/LongTanRadar  
**Audit date:** 2026-08-22  
**Baseline docs:** `docs/V4_OPTIMIZATION_AUDIT.md`, `docs/V4_BENCHMARK.md`  
**Rule:** No business-code changes in this document. Code is authoritative; README is not.

---

## 0. Executive Summary

V4 delivered **measurable cost infrastructure** and **partial call reduction** (gate, dynamic council, cache, context compression, incremental reuse). V5 must close the **Alpha & Cost Loop**: one canonical decision chain, ML in pre-research ranking, honest AI incremental alpha, experiment-gated optimizer, and frontend explainability.

**Critical gaps for V5:**

| Area | V4 status | V5 gap |
|------|-----------|--------|
| Canonical Decision | **Missing** | Dual display + dual LLM stacks; trading uses overwritten `picks` but payload retains roundtable |
| ML pre Top-N ranking | **Not wired** | `ml_prediction` is 0 at union sort; `weight_in_candidate_score: 0.35` unused |
| AI Incremental Alpha | **Partial / wrong definition** | Cohort bucket compare ≠ same-universe Top-K with/without AI |
| Research Gate tiers | **Binary pass/reject** | No `DEEP_RESEARCH` / `LIGHT_RESEARCH` / `NO_RESEARCH` |
| Optimizer | **Direct prod mutation** | `apply_proposal()` + `agent_overrides.yaml` every agent cycle |
| Benchmark | **Equal-weight proxy only** | No CSI300/中证500; honestly labeled |
| change_reason / call explain | **Missing** | No per-call or skip reason ledger |
| Alpha Dashboard | **Partial** | Agent cost panel only; no discovery/AI alpha UI |

---

## 1. Current Real Call Chains

### 1.1 Discovery → Candidate

```
build_leader_pool(cfg)                           # pool/builder.py — spot scan
  → NewsOpportunityEngine.discover()             # news/opportunity.py — no LLM
  → CandidateEngine.build_research_universe()    # candidate/__init__.py
       ProfitInflectionEngine + EventEngine enrich
       FactorEngine.asof_rows → leader_score
       merge news_discovery.news_candidates
       candidate_score = weighted(leader, profit, event, news, ml*10)
         ⚠ ml_prediction == 0 here (not predicted yet)
       sort → max_union(100) → max_research_pool(20)
       collect_stock() on top 20 only           # NewsIntelligenceEngine — no LLM
       rescore candidate_score (ml still 0 unless pre-set)
```

**News → Stock:** Works. `NewsOpportunityEngine` + union merge + `ResearchHypothesisEngine.from_event()`.

### 1.2 Research (dual AI stacks — still both run)

```
run_research()                                   # services/research.py
  → score_candidates → shortlist (top_n≈3)
  → run_roundtable(shortlist)                    # 4 LLM calls if ai.roundtable=true
  → CandidateEngine.build_research_universe()
  → ResearchSessionEngine.run_pool()
       MLRankingEngine.predict_rows()           # ML AFTER universe cut ⚠
       apply_research_gate()                     # pass/reject only
       per symbol (gate pass, max_council=12):
         build_snapshot()
         AICouncilEngine.run_parallel()          # dynamic roles + cache + incremental
         DebateEngine.run()                      # 0 LLM
         ChairmanEngine.summarize()              # 1 LLM (or cache / incremental reuse)
  → ReviewEngine.attribution_report()            # benchmark + ai_incremental_alpha
  → persist_report → data/reports/latest.json
```

### 1.3 Decision → Trading (no Canonical Decision object)

```
run_research picks path:
  1) roundtable → picks = roundtable.reviews
  2) if platform_reports: picks = mapped (platform chairman)  # OVERWRITES picks

execute_picks()                                  # services/trading.py
  → latest_picks / run_picks → picks_payload
  → if roundtable in payload OR committee_verdict on picks:
       approved = committee_approve | verdict==buy
  → PaperTradingBroker buy approved names
```

**Who controls trading today:**

- **Primary:** Platform Council mapped picks when `platform_reports` succeeds (`reason: platform_council`, chairman `SMALL_POSITION` + rating BUY/STRONG_BUY + RiskFilter).
- **Fallback:** Legacy Roundtable `committee_verdict` / `committee_approve` when platform path fails.
- **Problem:** Roundtable **still runs LLM** and remains in JSON/UI; `execute_picks` ai_review summary still says「投委会圆桌结论」even when picks are platform-sourced.
- **No** unified `CanonicalDecision` schema; fields scattered across pick rows and `platform_reports`.

### 1.4 Outcome → Attribution

```
ReviewEngine.attribution_report(platform_reports, panel)
  → equal_weight_benchmark_returns(panel, as_of)   # NOT CSI300
  → TrackingEngine.outcomes_for_report(..., benchmark_returns)
  → excess_return when benchmark key present
  → summarize_by_source / by_rating
  → compute_ai_incremental_alpha()                 # bucket cohort, not Top-K ablation
  → persist → data/research_outcomes.json
```

Paper fills are **not** linked to `TrackingEngine` outcomes (V4 finding still true).

### 1.5 Token / Cost Chain

```
LLMClient.chat()                                 # ai/client.py
  → reads resp.usage when provider returns it      # usage_source=actual
  → else estimate_tokens()                         # usage_source=estimated
  → AICostTracker.record() → data/ai/usage.jsonl
  → begin_cycle in run_research / agent run_cycle
GET /api/ai/cost → cycle + daily rollups
Agent.tsx cost panel (partial V4 Phase 10)
```

Missing vs V5 spec: `research_session_id`, `tokens_per_buy`, `cost_per_buy`, role skip reasons, `AICostLedger` as single named module (implemented as `cost_tracker.py`).

---

## 2. V4 Implementation Verification (Code Truth)

| V4 Phase | Claimed | Code reality | Verdict |
|----------|---------|--------------|---------|
| 1 Token tracking | ✓ | `cost_tracker.py`, `client._record_usage`, `usage.jsonl` | **Done** |
| 2 Role context compression | ✓ | `build_role_context()`, roundtable slim | **Done** |
| 3 Event cluster | ✓ | `news/cluster.py`, `event_clusters` in package | **Partial** — type+direction cluster, not full evidence registry |
| 4 Research cache | ✓ | `research/cache.py`, wired in `council.py` | **Done** — key lacks `news_version`, `as_of`, `candidate_hash` |
| 5 Dynamic council | ✓ | `dynamic_council.py`, `select_council_roles()` | **Done** — simpler than V5 role recipes |
| 6 Research gate | ✓ | `gate.py`, `session.run_pool()` | **Partial** — binary, not DEEP/LIGHT/NO |
| 7 Incremental research | ✓ | `incremental.py`, prior snapshot reuse | **Partial** — no `change_reason` enum |
| 8 Benchmark excess | ✓ | `benchmark.py` in `run_research` | **Done** — equal-weight universe proxy |
| 9 AI incremental alpha | ✓ | `compute_ai_incremental_alpha()` | **Partial** — not spec-compliant Top-K ablation |
| 10 Frontend cost | ✓ | `Agent.tsx` + `/api/ai/cost` | **Partial** — no alpha dashboard |
| 11 V4_BENCHMARK.md | ✓ | exists | **Done** |

**Still true from V4 audit (unchanged or only partially fixed):**

- Dual roundtable + council LLM on every research run.
- ML not in pre–Top-N union ranking.
- Optimizer directly mutates production config.
- Paper vs research outcome disconnect.
- `ab_compare()` not used for true AI Top-K experiment.

---

## 3. Required 20 Questions — Answers

### 1. 当前 Roundtable / Council 谁控制交易？

**Platform Council（Chairman mapped picks）** 在 `platform_reports` 成功时覆盖 `picks` 并驱动 `committee_approve`。  
**Legacy Roundtable** 仍运行 LLM、仍写入 report，但在 platform 成功时**不控制**最终 `picks`。  
`execute_picks()` 逻辑仍绑定 `roundtable` 字段存在性，易造成 UI/日志与真实决策源不一致。  
**不存在 Canonical Decision。**

### 2. 当前 ML 是否真的参与 Top-N 前排序？

**否。**  
`CandidateEngine.build_research_universe()` 在 union sort 时读取 `ml_prediction`，但该字段在 sort 前**恒为 0**（`predict_rows()` 仅在 `session.run_pool()` 内、universe 截断之后调用）。  
`research.yaml` 的 `ml_ranking.weight_in_candidate_score: 0.35` **未接入**；实际权重来自 `news.yaml` `candidate_weights.ml: 0.10` 且对初始排序无效。

### 3. 当前每 cycle 真实 LLM 调用次数是多少？

**无生产日志时无法给实测值**；仅能从代码推导上界：

| Component | Formula (configured) |
|-----------|-------------------|
| Roundtable | 4 (if `ai.roundtable=true`, shortlist≥1) |
| Council | `gate_passed ≤ max_council(12)` × `(dynamic_roles + chairman)` |
| Dynamic roles | ~1–4 / symbol (bear almost always) |
| Chairman | 1 / symbol (cache/incremental may skip) |
| Agent optimizer | +1 / agent cycle |

**Cold upper bound (no cache, all pass gate, 12 symbols, 4 roles+chair):** 4 + 12×5 = **64** research + 1 optimizer = **65**.  
**V4 前：** ~77.  
**V5 目标：** 15–30 — **尚未达到**（roundtable 4 calls always on + up to 12 symbols remain).

### 4. 当前真实 Token 是否能够获取？

**能，但有条件。**  
`LLMClient` 读取 OpenAI-compatible `resp.usage` → `usage_source=actual`；缺失时 `estimate_tokens()` → `estimated`。  
汇总：`GET /api/ai/cost`, `data/ai/usage.jsonl`.  
**未记录：** `research_session_id`, skip reasons, per-buy metrics.

### 5. 当前 Token 最大浪费在哪里？

1. **Roundtable still runs** while platform council is canonical for trading (~4 calls + fat payload every run).  
2. **Up to 12 council symbols** even after gate (gate top-3 always pass).  
3. **Dual news fetch** — roundtable `collect_stock` per shortlist name + union top-20 `collect_stock`.  
4. **Agent optimizer** every cycle (+ retrain risk).  
5. Cache miss on first run / context hash includes full role context blob (sensitive to minor field drift).

### 6. 当前 Cache 是否工作？

**是。** `ResearchCache` + `compute_context_hash` in `council._call_role` and `ChairmanEngine.summarize`.  
Cache hit → `source=cache`, `record_cache_save()` in cost tracker.  
**Gap:** Key does not include `news_version`, `as_of`, `candidate_hash` separately; uses slim `build_role_context` blob (good) but not V5 per-role hash isolation file.

### 7. 当前 Dynamic Council 是否存在？

**是。** `research/dynamic_council.py` — rule-based role selection; valuation skipped when `value_available=false` (also hard skip in `_call_role`).  
**Gap:** Not V5 profile recipes (e.g. news-heavy → Event+News+Bear); no per-role call explanation.

### 8. 当前 Research Gate 是否存在？

**是，简化版.** `research/gate.py` — binary pass/reject + `always_pass_top_n=3`.  
**Gap:** No `DEEP_RESEARCH` / `LIGHT_RESEARCH` / `NO_RESEARCH`; no token budget cap.

### 9. 当前 News → Stock 是否真正工作？

**是.** `NewsOpportunityEngine.discover()` → `news_candidates` → merged in `CandidateEngine` with hypothesis generation.  
Tests: `test_news_discovery*.py`, `test_phase10_research_cycle.py`.

### 10. 当前 News → Investment Hypothesis 是否存在？

**是.** `ResearchHypothesisEngine` — FACT / INFERENCE / HYPOTHESIS layers in `research/hypothesis.py`; used in discovery and candidate union.  
**Gap:** Not full V5 JSON schema (`mechanism`, `validation`, `invalidation` arrays); no standalone `investment_hypothesis` object on every news candidate in API.

### 11. 当前 Event Cluster 是否存在？

**是，基础版.** `news/cluster.py` — cluster by `(event_type, direction)`; `event_clusters` in `build_package()`.  
**Gap:** Not cross-title semantic merge; discovery still dedupes `(symbol, event_type)` only.

### 12. 当前 Outcome 是否真正计算 benchmark excess return？

**是，在 research run 路径.** `equal_weight_benchmark_returns()` passed to `attribution_report()`.  
**Honest limits:** Proxy benchmark (cross-section equal-weight), not CSI300/中证500; `benchmark_available` not exposed as flag; paper trades not in outcome loop.

### 13. 当前 AI Incremental Alpha 是否能够计算？

**部分.** `compute_ai_incremental_alpha()` runs in production attribution.  
**Not V5-compliant:** Compares `quant_only` vs other source buckets — **not** same-universe Baseline Top-K vs AI Top-K with identical rules.  
`ab_compare()` used internally but **not** for ranking ablation.

### 14. 当前 Attribution 是否进入生产流程？

**是.** `run_research()` → `ReviewEngine.attribution_report(..., persist=True)` → report JSON `research_outcomes`.

### 15. 当前 Optimizer 是否可能过拟合？

**是，风险仍在.**  
`agent.run_cycle()` → `propose_updates()` (LLM) → `persist_runtime_overrides` + `apply_proposal(cfg)` **directly** mutates strategy/pool/factor/ml weights from short paper history.  
No walk-forward experiment gate; can set `retrain: true`.

### 16. 当前最值得修改的 10 个问题

| # | Issue |
|---|-------|
| 1 | No Canonical Decision — dual stack confusion |
| 2 | Roundtable still burns LLM while not controlling trades |
| 3 | ML after universe cut — ranking leakage of intent |
| 4 | AI Incremental Alpha definition wrong |
| 5 | Optimizer direct prod mutation |
| 6 | Gate binary — no LIGHT/deep/token budget |
| 7 | No change_reason / call explanation |
| 8 | Paper outcomes disconnected from research attribution |
| 9 | No ML walk-forward weight experiment |
| 10 | Frontend shows roundtable + platform without decision source clarity |

### 17. 建议修改顺序 (V5 Phases)

| Order | Phase | Rationale |
|-------|-------|-----------|
| 1 | **Phase 1** Unified Canonical Decision | Fixes trust + UI/trade consistency |
| 2 | **Phase 2** ML ranking forward + walk-forward experiment | Alpha loop foundation |
| 3 | **Phase 3** AICostLedger enrichment + cost API | Measure before further cuts |
| 4 | **Phase 4** Research cache key upgrade | Safe token savings |
| 5 | **Phase 5** Dynamic Council V5 profiles + explanations | Quality-aware call reduction |
| 6 | **Phase 6** Research Gate tiers + budget | Hit 15–30 call target |
| 7 | **Phase 7** Incremental + change_reason | Daily loop |
| 8 | **Phase 8** News cluster + hypothesis schema | Discovery quality |
| 9 | **Phase 9** Outcome + true AI Incremental Alpha | Close loop |
| 10 | Frontend Alpha/Cost dashboard + candidate explain | Human audit |

### 18. 每项预计 Token 节省 (vs pre-V4 ~77 calls)

| Item | Est. call Δ | Est. token Δ |
|------|-------------|--------------|
| Roundtable → benchmark-only (no trade) | **−4 calls/run** | **−5~8%** |
| Gate tiers + max 8–10 deep | **−20~40%** council symbols | **−25~35%** |
| Dynamic council V5 profiles | **−30~40%** role calls | **−20~30%** |
| Cache warm (2nd run same day) | **−30~50%** on repeats | **−30~50%** |
| Incremental NO_CHANGE | **−20~40%** on daily | **−15~25%** |
| Context compression (done) | 0 calls | **−25~35%** input (already live) |
| **Cumulative realistic** | **76 → 18~28 calls** | **−55~70%** tokens |

### 19. 每项预计 Alpha 影响

| Item | Alpha impact |
|------|--------------|
| Canonical Decision | **Neutral/+** — removes wrong-stock trades from stack mismatch |
| ML forward ranking | **+/-** — may help or hurt; requires walk-forward, default low weight |
| Gate aggressive | **Risk −** — may drop serendipitous news names |
| Drop roundtable from trade path only | **Neutral** — if platform council is better calibrated |
| True AI incremental alpha metrics | **0** — measurement only |
| Optimizer experiment gate | **+** — reduces overfit-driven decay |
| Benchmark CSI300 vs EW | **Neutral** — better excess interpretability |

### 20. 风险

- Canonical migration breaks UI/tests expecting roundtable picks.  
- ML forward rank with stale model → wrong research pool.  
- Gate false negatives on news-only names.  
- Cache stale after material news event.  
- Incremental reuse hides prompt/model upgrade needs.  
- Equal-weight benchmark mis-ranks excess vs real index.  
- Sample size too small for alpha claims (paper ¥3000, few positions).  
- Optimizer experiment backlog if gate is too strict.

---

## 4. Top 10 Alpha Problems (Current)

1. **Dual decision stacks** — research/trade/UI disagree on authority.  
2. **ML not in union ranking** — research pool doesn't reflect model edge.  
3. **AI Incremental Alpha metric invalid** — bucket compare ≠ ablation.  
4. **Paper PnL ≠ research outcomes** — can't close loop on traded names.  
5. **Same-bar paper fill vs T+1 backtest** — attribution incomparable.  
6. **Optimizer overfit** — short paper window → weight churn.  
7. **Valuation/industry data absent** — fundamental edge mostly profit/event only.  
8. **News discovery rejects** — many `NOT_ENOUGH_EVIDENCE`; precision unmeasured in prod UI.  
9. **No role-level incremental value** — can't rank which council role earns keep.  
10. **Insufficient sample discipline** — no `INSUFFICIENT_SAMPLE` gate on alpha dashboards.

---

## 5. Top 10 Token Waste Points (Current, post-V4)

1. Legacy **roundtable 4 calls** every research run (trading uses platform).  
2. **Up to 12 × (roles+chair)** council calls after gate.  
3. **Roundtable + council** both fetch news/Kline for overlapping symbols.  
4. **Agent optimizer** + optional **retrain** every cycle.  
5. Chairman re-synthesis when incremental could reuse (partially fixed).  
6. First-run **cache miss** on full research day.  
7. **Gate always_pass_top_n=3** forces LLM on weak tail if they rank top-3.  
8. Estimated tokens when provider omits usage (cost uncertainty).  
9. Roundtable multi-symbol JSON payload to each role.  
10. No **token budget** hard stop — runaway on API errors/retries.

---

## 6. V5 Acceptance Checklist (Pre-work Status)

| Item | Status |
|------|--------|
| Roundtable 不直接控制交易 | ⚠️ Partial — overwrites when platform OK, but roundtable still runs |
| 唯一 Canonical Decision | ❌ |
| Paper 使用 Canonical Decision | ⚠️ De facto platform picks, not schema |
| ML 在 Top-N 前参与排序 | ❌ |
| ML walk-forward evaluation | ❌ |
| LLM Token 可统计 | ✅ |
| LLM Cost 可统计 | ✅ |
| Research Cache 工作 | ✅ |
| Context Hash 工作 | ✅ (role context blob) |
| Dynamic Council 工作 | ✅ |
| Research Gate 工作 | ⚠️ Binary only |
| Incremental Research 工作 | ⚠️ No change_reason |
| News Event Cluster 工作 | ⚠️ Basic |
| News → Hypothesis 工作 | ✅ |
| News → Candidate 工作 | ✅ |
| Outcome 自动记录 | ✅ (research reports) |
| Benchmark 自动计算 | ⚠️ EW proxy |
| Excess Return 自动计算 | ✅ when panel≥2 |
| AI Incremental Alpha 可计算 | ⚠️ Wrong definition |
| Discovery Attribution 可计算 | ⚠️ Partial buckets |
| AI Cost Efficiency 可计算 | ❌ |
| Optimizer 不直接改生产 | ❌ |
| 测试覆盖 V5 list | ⚠️ ~16 tests, missing decision consistency / ML forward / ledger |
| 无未来函数 | ✅ (news filter_asof, etc.) |

---

## 7. Key File Index

| Area | Paths |
|------|-------|
| Research orchestration | `services/research.py`, `services/picks.py` |
| Trading / paper | `services/trading.py`, `brokers/paper.py` |
| Candidate union | `candidate/__init__.py` |
| ML ranking | `ml/ranking.py`, `research/session.py` |
| Roundtable | `ai/roundtable.py` |
| Council | `research/council.py`, `session.py` |
| Gate / cache / incremental | `research/gate.py`, `cache.py`, `incremental.py`, `dynamic_council.py` |
| Intel / context | `research/intel_package.py` |
| News | `news/opportunity.py`, `engine.py`, `cluster.py`, `hypothesis.py` |
| Outcome / alpha | `research/tracking.py`, `benchmark.py` |
| Cost | `ai/cost_tracker.py`, `ai/client.py`, `api/app.py` |
| Optimizer | `ai/optimizer.py`, `services/agent.py` |
| Config | `config/research.yaml`, `news.yaml`, `default.yaml` |
| Frontend | `web/src/pages/Research.tsx`, `Agent.tsx` |
| Tests | `tests/test_*` (16 files) |

---

## 8. Phase 0 Exit

- [x] Re-read V4 audit + benchmark  
- [x] Re-scan codebase post-V4 commit `189013f`  
- [x] Document real decision / trading / token / outcome chains  
- [x] Answer 20 required questions  
- [x] Rank Alpha + Token issues  
- [x] Propose V5 modification order with savings/alpha/risk  
- [x] **No business code modified**

**Next step (await confirmation):** **V5 Phase 1 — Unified Canonical Decision** + `decision_consistency` test.

---

## 9. README vs Code (still divergent)

| README / config claim | Code |
|-----------------------|------|
| `ml_ranking.weight_in_candidate_score: 0.35` | **Unused** — `news.yaml` weights; ML zero at sort |
| Single committee | **Two LLM committees** per run |
| Token visibility | **Implemented** (post-V4) |
| AI helps trading | **Platform chairman** + roundtable legacy coexist |
