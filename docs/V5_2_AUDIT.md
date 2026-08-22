# V5.2 Phase 0 Audit — Alpha Validation & Cost Optimization

**Project:** [LongTan Radar](https://github.com/Skeiro666/LongTanRadar)  
**Audit date:** 2026-08-22  
**Phase:** 0 — read-only audit + **post-audit gap closure（2026-08-22 二轮）**  
**Code baseline:** `main` post-`9f7101a`（outcome truth · LLM budget · lifecycle 扩展 · 文档债）  
**Rule:** Code is authoritative; README / 旧 V5 文档 / 本文件历史段落均可能过时。

---

## 0. Executive Summary

LongTanRadar V5 已建立 **Canonical Decision → Paper Trading** 主链；V5.2 在 **Benchmark 真值、Token 降本、Alpha 归因** 上已 substantial 落地。二轮补丁闭合了 outcome truth 优先级、LLM 硬预算、完整 Event lifecycle 与文档债；**50% 降本仍缺生产 before/after 基准表**。

| 领域 | 当前代码状态 | 相对 V5.2 规格仍缺 |
|------|-------------|-------------------|
| Benchmark | ✅ 双轨 CSI300 + EW；`benchmark_snapshot`；`market_alpha` / `selection_alpha` | ML 训练 target 与 attribution benchmark 可能不一致 |
| Paper ↔ Outcome | ✅ `outcome_truth.py`：`paper_fill > signal_close`；`primary_horizons`；`/api/pnl` `research_link` | 非单一 merged PnL 表；exit_time/exit_price 未全链 |
| Roundtable | ✅ `sampled`/`scheduled`/`disabled`；默认 `sampled` | 未量化证明 50% calls 下降 |
| AI Incremental Alpha | ✅ canonical Top-K ablation；`ranking_method=heuristic_rating_to_score` | — |
| Event Lifecycle | ✅ NEW/CONFIRMED/DEVELOPING/PRICED_IN/MONETIZING/RESOLVED/INVALIDATED/REJECTED | — |
| Expected Return | ⚠️ `investment_hypothesis.expected_excess_return`（多数 available=false） | 无顶层 `candidate.expected_excess_return` 三元组 |
| Token 降本 | ✅ Gate/Dynamic/Cache/Incremental/Chairman/Roundtable + **`llm_budget` 硬停** | §36 before/after 生产基准表 |
| 实验框架 | ✅ role ablation + model benchmark + `V5_2_ML_WEIGHT_EXPERIMENT.md` | 无 Role×Model 在线 A/B |
| Dashboard | ✅ Research Alpha + portfolio attribution + cache hit rate | 缺独立 Cost Dashboard 全指标页 |

**最大 Token 浪费（仍成立）：** Council 全池串行 + Bear 常开 + 首日零 cache。  
**最大 Alpha 风险（仍成立）：** Paper PnL 与 Research Outcome 并行；Event lifecycle 不完整导致 Price-In 特征未进决策链。

---

## 1. 当前真实架构

```
Market Data (akshare / Parquet panel)
    ↓
Pool / Screen (leader, event, profit)
    ↓
NewsOpportunityEngine.discover(as_of)     [0 LLM · 规则 Event 抽取]
    ↓
CandidateEngine.build_research_universe(as_of)
    MLRankingEngine.predict_rows()        [Top-N 截断前]
    Union(100) → Research(20) → collect_stock(as_of)  [0 LLM · HTTP 新闻]
    ↓
run_research()  [`services/research.py`]
    ├─ score_candidates → shortlist
    ├─ should_run_roundtable()            [sampled/scheduled/disabled · ~0–5 LLM]
    ├─ ResearchSessionEngine.run_pool()
    │     ResearchGate (deterministic)
    │     DynamicCouncil.plan_council()
    │     AICouncilEngine + ResearchCache + Incremental
    │     ChairmanEngine (slim context)
    ├─ build_canonical_decisions()
    ├─ ReviewEngine.attribution_report()
    │     dual benchmark · market/selection alpha
    │     role_ablation · model_benchmark (experimental)
    └─ persist → latest.json / snapshots / progress API
    ↓
execute_picks() → extract_trading_decisions(canonical) → PaperTradingBroker
    ↓
Agent loop (optional) → optimizer experiment (auto_apply=false)
```

**双 AI 栈（架构事实，未消除）：**

1. **Production：** Platform Council → Canonical Decision → Paper  
2. **Benchmark / AB：** Legacy Roundtable（`benchmark_only`，不控交易；生产默认 **sampled** 降频）

---

## 2. 当前真实 LLM 调用链

### 2.1 `run_research()` 单次完整研究

| 阶段 | 模块 | LLM 次数（典型） | 跳过条件 |
|------|------|------------------|----------|
| News discovery | `news/opportunity.py` | 0 | — |
| Legacy roundtable | `ai/roundtable.py` | 0–5 | `disabled` / `sampled` / `scheduled` |
| Council per symbol | `research/council.py` | 1–5 roles × N + 1 chair | Gate reject · Dynamic skip · Cache · Incremental NO_CHANGE |
| Debate | `research/debate.py` | 0 | 规则模板 |
| Chairman | `ChairmanEngine` | 0–1/股 | Cache · Incremental reuse |
| Optimizer（研究路径） | — | 0 | — |

**预算封顶：** `research_gate.max_llm_calls: 30` + **`llm_budget`**（`max_input_tokens` / `max_output_tokens` / `max_cost_usd` 硬停，见 `llm_budget.py`）

### 2.2 Agent 循环（独立）

| 阶段 | LLM |
|------|-----|
| 嵌入 `run_research()` | 同上 |
| `propose_updates()` | +1 |

### 2.3 确定性路径（0 LLM）

`ResearchGate` · `DynamicCouncil` · `DebateEngine` · `build_canonical_decision()` · Gate reject → `_gate_skip_report()`

---

## 3. 当前真实 Token 消耗点（按浪费优先级）

| 排名 | 消耗点 | 位置 | 估计占比 | V5.2 缓解 |
|------|--------|------|----------|-----------|
| 1 | Council 全池串行 | `session.run_pool()` | ~55–70% calls | Gate · Dynamic · Cache · Incremental |
| 2 | Legacy Roundtable | `research.py` + `should_run_roundtable()` | ~0–25% | **sampled 默认**（每 10 session / 日 1 次） |
| 3 | Bear 几乎 always-on | `dynamic_council.py` | ~10–15% role | Dynamic profile |
| 4 | 大 context（Event role news） | `intel_package.build_role_context()` | Token 体积 | 压缩 + evidence_ids |
| 5 | Per-stock news fetch ×20 | `candidate/__init__.py` | 非 LLM · 放大 context | as_of 已传 |
| 6 | Agent optimizer proposal | `agent.py` | +1/cycle | 与研究解耦 |

**V5.2 已生效节省机制：** Gate · DynamicCouncil · ResearchCache（role-specific hash）· Incremental · Chairman slim · Roundtable sampled · **LLM budget hard stop**。

**已实现（规格 §27）：** `llm_budget.py` — `max_llm_calls` / `max_input_tokens` / `max_output_tokens` / `max_cost_usd`；`0` = 该维度不限。

---

## 4. 当前真实 Alpha 链

```
Discovery tags (quant / news / event / profit / ml)
    ↓
candidate_score  [cross-sectional rank · 非 probability · 非 expected return]
    ↓
ResearchGate → NO_RESEARCH | LIGHT | DEEP  [deterministic]
    ↓
DynamicCouncil + Chairman → research_rating / trading_action
    ↓
build_canonical_decision() → committee_approve
    ↓
Paper fill (if approve)
    ↓
TrackingEngine.outcomes_for_report()
    total_return · market_alpha · selection_alpha · excess_return(legacy primary)
    ↓
Attribution:
    discovery_attribution · by_source_bucket
    ai_incremental_alpha (canonical Top-K ablation)
    ai_incremental_alpha_legacy (cohort · 参考)
    role_ablation · model_benchmark (experimental)
    ↓
Cost ledger → alpha_per_100k_tokens (dashboard)
```

**仍缺闭环环节：**

- Research Outcome 与 `/api/pnl` **两套 truth**  
- `expected_excess_return` 多数 `available=false`，无法做「预测 vs 实现」验收  
- AI ranking 为 heuristic（rating→score），未标注于所有消费路径

---

## 5. 当前 Benchmark 实现

**代码：** `src/ashare/research/benchmark.py`

| 概念 | 实现 | 字段 |
|------|------|------|
| Market Benchmark | CSI300 (`000300`) | `market_benchmark_return` → `market_alpha` |
| Universe Benchmark | Equal-weight research panel | `universe_benchmark_return` → `selection_alpha` |
| Snapshot | `benchmark_snapshot()` | `requested, actual, index, fallback, fallback_reason, as_of` |

**配置：** `config/research.yaml` → `tracking.benchmark: csi300`, `benchmark_fallback: equal_weight_universe`

**前端：** Research Alpha tab 展示 requested/actual/fallback（`Research.tsx`）

**仍存在问题：**

1. `excess_return` 仍为 **单一 primary bench**（market 优先），与双 Alpha 并存 — 文档须说明勿混读  
2. ML 训练（`config/models.yaml`）target 可能仍用 EW — **与 attribution 主 bench 不一致风险**  
3. Progress 文案偶发「CSI300」而 runtime 为 fallback — 需保持 UI 诚实（已部分修复）

---

## 6. 当前 Paper → Outcome 链

| 环节 | 模块 | 状态 |
|------|------|------|
| 决策 | `canonical_decision.py` | ✅ Platform Chairman → canonical |
| 执行 | `trading.execute_picks()` | ✅ 优先 `canonical_decisions` |
| Outcome entry | `tracking.outcomes_for_report()` | ✅ research_time close |
| Paper 链接 | `execution_tracking.attach_paper_execution()` | ✅ fill 匹配 + horizons_from_fill |
| ID 链 | `execution_tracking` | ✅ decision_id / snapshot_id / signal_time / fill_time 等 |

**缺口（P0 未完全闭合）：**

| 字段 | 状态 |
|------|------|
| exit_time / exit_price | ❌ 未系统化 |
| 单一 PnL truth | ❌ `/api/pnl` vs `research_outcomes` 并行 |
| 无 fill 时 | `execution.available=false`，outcome 仍按 signal close 计算 |

---

## 7. 当前 News → Event → Candidate 链

```
discover(as_of) → classify → link → extract_events
    ↓
ResearchHypothesisEngine → FACT/INFERENCE/HYPOTHESIS + investment_hypothesis
    ↓
EvidenceRegistry (E…)
    ↓
NewsCandidate → CandidateEngine union
    ↓
annotate_news_candidate_price(as_of) → price_in_risk · price_in_score
    ↓
apply_event_lifecycle() → NEW | CONFIRMED | DEVELOPING | PRICED_IN | MONETIZING | RESOLVED | INVALIDATED | REJECTED
```

| 能力 | 状态 |
|------|------|
| News → Candidate | ✅ |
| News → Event | ✅ 规则 `extract_events()` |
| Event → Hypothesis | ✅ 模板 + layers |
| Price-In | ✅ `price_in_risk` 警告 · `price_in_score` 0–1 |
| Event Lifecycle（完整） | ✅ 8 态状态机 | `event_lifecycle.py`, `test_v5_2_event_lifecycle.py` |
| expected_excess_return | ⚠️ 仅 hypothesis 内 · expectation_gap 有数据时 available |
| as_of 泄漏 | ✅ union 路径 `collect_stock(as_of=)` 已修复 |

---

## 8. Cache 实际命中情况

**实现：** `research/cache.py` — disk JSON · TTL 24h

**V5.2 改进：** `project_context_for_hash(role_id, context)` — role 专用字段投影

**Chairman cache key：** `role_reports + evidence_ids + debate`

**未覆盖：** Legacy Roundtable

**生产可见性：** cache hit rate 在 `cost_tracker` cycle summary；**未写入 research snapshot 标准字段**

**估计命中率：** 重复 as_of + 无变化 → **40–80%** council 节省；首日/新 symbol → **≈0%**

---

## 9. Dynamic Council 实际调用情况

**实现：** `research/dynamic_council.py` → `plan_council()`

| Profile | 典型 Roles |
|---------|------------|
| profit_inflection | bear, fundamental, quant |
| major_news / major_event | bear, event, (+quant) |
| valuation_available | bear, quant, valuation |
| default | bear + 条件 quant |

- Bear：**几乎 always-on**  
- Valuation：**仅 value_available**  
- 无独立 **News role**（由 Event role 覆盖 news 候选）  
- Skip → `skipped_role_opinion()` 0 LLM

**相对 Full Council：** 约 **20–50%** role call 节省（视 profile）

---

## 10. 二十项审计问答（当前代码）

| # | 问题 | 结论 | 证据 |
|---|------|------|------|
| 1 | 真实交易决策谁产生？ | **Platform Council Chairman → Canonical Decision** | `session.py`, `canonical_decision.py` |
| 2 | Paper 是否只用 Canonical？ | **是（设计 + 默认路径）**；legacy committee_verdict 为 fallback | `trading.py:execute_picks()` |
| 3 | Legacy Roundtable 仍消耗 LLM？ | **可消耗，但生产默认 sampled 降频** | `benchmark.should_run_roundtable()`, `default.yaml` |
| 4 | ML 在 Top-N 截断前排序？ | **是** | `candidate/__init__.py` ML before union cut |
| 5 | News 能否产生 Candidate？ | **能** | `opportunity.py`, union merge |
| 6 | News 能否形成 Event？ | **能** | `news/extract.py` |
| 7 | Event 能否形成 Hypothesis？ | **能** | `research/hypothesis.py` |
| 8 | ResearchGate 是否减少 LLM？ | **是** — deterministic · reject=0 LLM | `gate.py`, `session.py` |
| 9 | Dynamic Council 是否减少 Role？ | **是** | `dynamic_council.py` |
| 10 | ResearchCache 是否真正命中？ | **机制有效 + role-specific hash**；命中率依赖重复运行 | `cache.py`, `test_v5_2_cost_optimization.py` |
| 11 | Incremental 是否避免重复？ | **是** — NO_CHANGE → 0 refresh | `incremental.py` |
| 12 | Chairman 是否收到完整 Snapshot？ | **否** — slim `role_reports + evidence_ids` | `intel_package.build_chairman_context()` |
| 13 | Token Ledger 是否真实 usage？ | **混合** — actual/estimated/cache；cost 始终估算 | `cost_tracker.py` |
| 14 | Benchmark 是否明确？ | **是（V5.2）** — snapshot + 双 alpha + UI fallback | `benchmark.py`, `tracking.py` |
| 15 | Outcome 与 Paper Fill 连接？ | **部分** — attach 已接线；非唯一 PnL truth | `execution_tracking.py` |
| 16 | AI Incremental Alpha 同 universe？ | **是（canonical）**；legacy cohort 保留为 `_legacy` | `tracking.attribution_report()` |
| 17 | Attribution 区分 Quant/News/Event/Profit/ML？ | **部分** — discovery tags；无独立 ML alpha 层 | `summarize_discovery_sources()` |
| 18 | Optimizer 能否改生产参数？ | **默认不能** — `auto_apply: false` + experiment gate | `optimizer_experiment.py` |
| 19 | 最大 Token 浪费？ | **Council 全池 + 无 token 硬预算** | §3 |
| 20 | 最大 Alpha 风险？ | **双 PnL truth + heuristic AI rank + lifecycle 简化** | §4、§6 |

---

## 11. P0 / P1 / P2 问题清单

### P0 — 正确性 + 最大结构性浪费

| ID | 问题 | V5.2 状态 | Token Δ（估） | Alpha 影响 | 风险 |
|----|------|-----------|---------------|------------|------|
| P0-1 | Benchmark 分层 + Snapshot + UI | ✅ 已实现 | 0 | 高→已缓解 | 低 |
| P0-2 | Market / Selection Alpha | ✅ 已实现 | 0 | 高→已缓解 | 低 |
| P0-3 | Roundtable sampled/scheduled | ✅ 已实现 | −15–25% calls | 低 | 中 |
| P0-4 | Paper ↔ Outcome 统一 truth | ⚠️ 部分（`outcome_truth` + `research_link`） | 0 | 中 | 低 |
| P0-5 | 前端 Benchmark 诚实展示 | ✅ 已实现 | 0 | 中 | 低 |

### P1 — 降本 + 语义

| ID | 问题 | V5.2 状态 | Token Δ（估） | Alpha 影响 | 风险 |
|----|------|-----------|---------------|------------|------|
| P1-1 | Role-specific context hash | ✅ 已实现 | +10–25% hit | 低 | 低 |
| P1-2 | Chairman 压缩 | ✅ 已实现 | −20–40% chair in | 中 | 中 |
| P1-3 | Evidence 摘要注入（非全文） | ⚠️ 部分 | −10–30% event | 低 | 低 |
| P1-4 | candidate_score 语义文档 | ✅ `snapshot.candidate_score_meta` + intel_package | 0 | 低 | 低 |
| P1-5 | expected_excess_return | ⚠️ 部分 | 0 | 高 | 中 |
| P1-6 | Event Lifecycle 全状态机 | ✅ 已实现 | 0 | 低 | 低 |
| P1-7 | collect_stock(as_of) | ✅ 已实现 | 0 | 高→已缓解 | 低 |
| P1-8 | ML weight walk-forward | ✅ test + `V5_2_ML_WEIGHT_EXPERIMENT.md` | 0 | 低 | 低 |
| P1-9 | LLM token/cost 硬预算 | ✅ `llm_budget.py` | 可变 | 中 | 低 |

### P2 — 实验

| ID | 问题 | V5.2 状态 | Token Δ | Alpha 影响 | 风险 |
|----|------|-----------|---------|------------|------|
| P2-1 | ai_incremental_alpha = topk | ✅ 已实现 | 0 | 高 | 低 |
| P2-2 | Role Ablation | ⚠️ offline experimental | +实验成本 | 高 | 中 |
| P2-3 | Role × Model benchmark | ⚠️ token rollup · 非在线 A/B | +实验成本 | 中 | 中 |
| P2-4 | Optimizer experiment gate | ✅ 已有 | 0 | 中 | 低 |

**50% Token 目标可达性（估）：**

- Roundtable sampled + Gate + Dynamic + Cache + Chairman：**理论可达 50%+**  
- **缺生产 before/after 基准表**（规格 §36）— 需跑固定 as_of 对比实验

---

## 12. 测试覆盖（相对规格 §33）

| 测试项 | 状态 | 文件 |
|--------|------|------|
| Benchmark resolution / fallback | ✅ | `test_v5_2_benchmark.py`, `test_csi300_execution.py` |
| Market / Selection Alpha | ✅ | `test_v5_2_benchmark.py` |
| Canonical Decision | ✅ | `test_decision_consistency.py` |
| Paper Fill → Outcome | ✅ 部分 | `test_csi300_execution.py` |
| ML Weight walk-forward | ✅ | `test_ml_weight_experiment.py` |
| Research Gate | ✅ | `test_research_gate.py` |
| Dynamic Council | ⚠️ 部分 | `test_research_cache.py` |
| Context Hash (role-specific) | ✅ | `test_v5_2_cost_optimization.py` |
| Incremental NO_CHANGE | ✅ | `test_incremental_research.py` |
| Event Lifecycle | ✅ 8 态 | `test_v5_2_event_lifecycle.py` |
| Price-In | ✅ | `test_price_reaction.py` |
| AI Incremental (same universe) | ✅ | `test_v5_2_alpha_ablation.py` |
| Role Ablation | ✅ experimental | `test_v5_2_alpha_ablation.py` |
| Model benchmark rollup | ✅ | `test_v5_2_alpha_ablation.py` |
| Token Budget (tokens/cost cap) | ✅ | `test_v5_2_outcome_budget.py` |
| Outcome truth (paper > signal) | ✅ | `test_v5_2_outcome_budget.py`, `outcome_truth.py` |
| Optimizer Safety | ✅ | `test_phase9_alpha_optimizer.py` |
| Future news rejection | ⚠️ 部分 | `test_news_intelligence.py` |

---

## 13. 实施风险（后续 Phase）

1. **Chairman 过度压缩** — 需 shadow 质量对比  
2. **Roundtable 降频** — 失去每轮 AB；依赖 scheduled 可复现  
3. **双 PnL truth 迁移** — 历史对比口径变化  
4. **Token 硬预算** — 可能跳过边缘 HIGH candidate（须优先级队列）  
5. **Role×Model 在线实验** — 成本上升；须 experimental 标注

---

## 14. 与 V5 / V5.2 文档对照

| 文档 | 状态 |
|------|------|
| `V5_2_AUDIT.md` | 本文件 |
| `V5_2_BENCHMARK.md` | ✅ |
| `V5_2_ALPHA_ATTRIBUTION.md` | ✅ |
| `V5_2_EVENT_LIFECYCLE.md` | ✅（简化 lifecycle） |
| `V5_2_COST_OPTIMIZATION.md` | ✅ |
| `V5_2_COMPLETE.md` | ✅ 总览 |
| `V5_2_NEWS_EVENT_LIFECYCLE.md` | ✅ |
| `V5_2_TOKEN_COST.md` | ✅ |
| `V5_2_MODEL_ROUTING.md` | ✅ |
| `V5_2_ML_WEIGHT_EXPERIMENT.md` | ✅ |
| `V5_2_OUTCOME_TRUTH.md` | ✅ |

---

## 15. Phase 0 结论

**Phase 0 审计 + 二轮 gap closure 完成。**

**已落地：** 双 Benchmark · Roundtable 采样 · Paper execution IDs · **Outcome truth** · **LLM budget** · Event lifecycle 8 态 · Cache/Chairman 压缩 · Canonical AI incremental alpha · 实验性 ablation/model rollup · Dashboard portfolio α / cache hit · 完整 V5.2 文档集。

**建议下一优先级（V5.2+）：**

1. **P0-4 完全闭合** — 单一 merged PnL 表 + exit 字段  
2. **§36 Before/After 基准表** — 固定 as_of 跑一轮量化 50% 目标  
3. **Shadow chairman** — 压缩后质量 A/B  
4. **Role×Model 在线实验** — scheduled A/B（experimental）

**本阶段禁止（仍有效）：**

- 新增 AI Role / Prompt 堆叠 / 新闻源 / 因子 / 复杂 Agent  
- Optimizer 自动改生产  
- Dashboard 造假数字

---

## 附录 A — 关键文件索引

| 主题 | 路径 |
|------|------|
| 研究编排 | `src/ashare/services/research.py` |
| Benchmark | `src/ashare/research/benchmark.py` |
| Outcome / Alpha | `src/ashare/research/tracking.py` |
| Paper 执行 | `src/ashare/research/execution_tracking.py` |
| Outcome truth | `src/ashare/research/outcome_truth.py` |
| Event Lifecycle | `src/ashare/news/event_lifecycle.py` |
| LLM budget | `src/ashare/research/llm_budget.py` |
| PnL research link | `src/ashare/services/pnl.py` |
| Cache | `src/ashare/research/cache.py` |
| Chairman / Context | `src/ashare/research/intel_package.py` |
| Role Ablation | `src/ashare/research/role_ablation.py` |
| Model Benchmark | `src/ashare/research/model_benchmark.py` |
| Cost Ledger | `src/ashare/ai/cost_tracker.py` |
| Gate | `src/ashare/research/gate.py` |
| 配置 | `config/research.yaml`, `config/default.yaml` |

---

*Phase 0 Audit — 2026-08-22 二轮 gap closure 已合入 main。*
