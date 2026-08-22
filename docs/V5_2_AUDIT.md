# V5.2 Phase 0 Audit — Alpha Validation & Cost Optimization

**Project:** LongTan Radar  
**Repo:** https://github.com/Skeiro666/LongTanRadar  
**Audit date:** 2026-08-22  
**Phase:** 0 — **read-only audit, no business-code changes**  
**Baseline:** V5 commit `2abeee6` (Canonical Decision, ML ranking, progress API, Persona UI)  
**Rule:** Code is authoritative; README and stale comments are not.

---

## 0. Executive Summary

V5 已建立 **Canonical Decision → Paper Trading** 主链、ResearchGate / DynamicCouncil / Cache / Incremental 等降本机制，以及 **CSI300 + fallback** 的 benchmark 解析。但 V5.2 目标（**可验证 Alpha 闭环 + 50% Token 降本**）仍有关键缺口：

| 领域 | V5 现状 | V5.2 缺口 |
|------|---------|-----------|
| Benchmark 语义 | `resolve_benchmark_pack()` 可 CSI300 或 fallback EW | **未写入 Snapshot**；UI/文案仍混称；**无 Market vs Selection Alpha 分层** |
| Paper ↔ Outcome | `attach_paper_execution()` 已接线 | **非唯一 truth**；Research outcome 与 Paper PnL 仍并行；缺 `decision_id` 级全链路 |
| Legacy Roundtable | 每轮仍 ~5 LLM，`benchmark_only` | **最大结构性 Token 浪费**；无 `scheduled`/`sampled` |
| AI Incremental Alpha | `ai_topk_ablation` 同 universe ✅ | `ai_incremental_alpha` 仍为 **cohort 对比** ⚠️ |
| Expected Return | 不存在 | 无 `expected_excess_return` / `confidence` 字段 |
| Event Lifecycle | 规则链完整 | **无 NEW→PRICED_IN→RESOLVED 状态机** |
| Context Hash | 按 role + context dict | **非 role 专用 hash**；无关字段变化导致 cache miss |
| Optimizer | `auto_apply: false` 默认 | 安全 ✅；缺 walk-forward **批准门禁**文档化 |

**本阶段建议顺序：** P0 Benchmark 真值 → P0 Roundtable 采样 → P0 Outcome 统一 → P1 Gate/Cache/Chairman → P2 Ablation/Model routing。

---

## 1. 当前真实架构

```
Market Data (akshare)
    ↓
Pool / Screen (leader, event, profit)
    ↓
NewsOpportunityEngine.discover()          [无 LLM]
    ↓
CandidateEngine.build_research_universe()
    MLRankingEngine → candidate_score → Union(100) → Research(20)
    ↓
run_research()
    ├─ score_candidates → shortlist        [因子 Top-N，供 Roundtable]
    ├─ run_roundtable(shortlist)           [Legacy ~5 LLM，benchmark_only]
    ├─ ResearchSessionEngine.run_pool()    [Gate → DynamicCouncil → Chairman]
    ├─ build_canonical_decisions()
    ├─ ReviewEngine.attribution_report()   [Outcome + Alpha]
    └─ persist → latest.json / snapshots
    ↓
execute_picks() → extract_trading_decisions() → PaperTradingBroker
    ↓
Agent loop (optional) → propose_updates → experiment (not prod by default)
```

**双 AI 栈（V5 遗留问题）：**

1. **Production：** Platform Council（DynamicCouncil + Chairman）→ Canonical Decision  
2. **Benchmark：** Legacy Roundtable（dragon/event/risk/chair）→ 不控交易，但 **每轮仍调用**

---

## 2. 当前真实 LLM 调用链

### 2.1 `run_research()` 单次完整研究

| 阶段 | 模块 | LLM 次数（典型） | 是否可跳过 |
|------|------|------------------|------------|
| News discovery | `news/opportunity.py` | 0 | — |
| Legacy roundtable | `ai/roundtable.py` | ~4–5 | 仅 `roundtable_mode=disabled` |
| Council per symbol | `research/council.py` | 1–5 roles × N + 1 chair | Gate / Dynamic / Cache / Incremental |
| Debate | `research/debate.py` | 0 | — |
| Optimizer | `services/agent.py` | 0（研究路径） | — |

**Council 单股（最坏）：** 5 analyst roles + 1 chairman = 6 calls  
**Council 池（max_council=12, max_llm_calls=30）：** 预算封顶 30 次 session 级 LLM（含 chair）

### 2.2 Agent 循环（独立）

| 阶段 | LLM |
|------|-----|
| `run_research()` 嵌入 | 同上 |
| `propose_updates()` | +1 |
| Roundtable（若 agent 也触发 research） | 同上 |

### 2.3 确定性路径（0 LLM）

- `ResearchGate.evaluate_research_gate()` — 纯规则  
- `DynamicCouncil.plan_council()` — 纯规则  
- `DebateEngine` — 模板/规则  
- `build_canonical_decision()` — 规则  
- Gate reject → `_gate_skip_report()` — 0 LLM

---

## 3. 当前真实 Token 消耗点（按浪费优先级）

| 排名 | 消耗点 | 位置 | 估计占比 | 说明 |
|------|--------|------|----------|------|
| 1 | **Legacy Roundtable 每轮必跑** | `services/research.py:204–225` | ~15–25% calls | 与 Council 重复辩论，仅 benchmark |
| 2 | **Council 全池串行** | `session.py` → `run_pool()` | ~60–75% | 12 股 × 多 role；fresh run 无 cache |
| 3 | **Bear 几乎 always-on** | `dynamic_council.py:91–98` | ~10–15% role calls | DEFAULT_BEAR 兜底 |
| 4 | **大 context 输入** | `intel_package.py` → `build_role_context()` | Token 量 | 每 role 仍含较多 news/quant |
| 5 | **Chairman 重复阅读** | `build_chairman_context()` | 中等 | 已压缩，仍含 opinions 全文 |
| 6 | **Per-stock news fetch（20 只）** | `candidate/__init__.py:237` | 非 LLM | 放大 context 体积 |
| 7 | **Agent optimizer proposal** | `agent.py` | +1 call/cycle | 与研究无关时仍耗 |

**V5 已有但未充分生效的节省：** Gate（拒研）、DynamicCouncil（减 role）、ResearchCache（24h TTL）、Incremental（NO_CHANGE → 0 calls）。

---

## 4. 当前真实 Alpha 链

```
Discovery (quant / news / event / profit tags)
    ↓
candidate_score (cross-sectional rank, NOT probability)
    ↓
ResearchGate (NO / LIGHT / DEEP tier)
    ↓
DynamicCouncil + Chairman → research_rating / trading_action
    ↓
build_canonical_decision() → committee_approve
    ↓
Paper fill (if approve)
    ↓
TrackingEngine.outcomes_for_report() → actual_return, excess_return (single benchmark)
    ↓
Attribution: by_source_bucket, discovery_sources, ai_topk_ablation, ai_incremental_alpha
```

**缺口：**

- 无 **Market Alpha**（vs CSI300）与 **Selection Alpha**（vs EW universe）分列  
- `excess_return` 仅减 **一个** benchmark（CSI300 或 fallback EW，非两者同时）  
- Legacy `ai_incremental_alpha` = quant_only vs council_reviewed **不同 cohort**  
- 无 **expected_excess_return** 前向字段，无法验证「预测 vs 实现」

---

## 5. 当前 Benchmark 实现

**代码：** `src/ashare/research/benchmark.py`

| 方法 | 含义 |
|------|------|
| `csi300_benchmark_returns()` | 000300 指数 forward return |
| `equal_weight_benchmark_returns()` | 研究 panel 截面等权均值 |
| `resolve_benchmark_pack()` | 配置 `tracking.benchmark: csi300`，失败则 `fallback_from: csi300_unavailable` |

**配置：** `config/research.yaml` → `tracking.benchmark: csi300`, `benchmark_fallback: equal_weight_universe`

**问题（V5.2 P0）：**

1. **Snapshot 未持久化** `requested / actual / fallback / fallback_reason` 标准结构  
2. **Attribution 文案**仍写 “Excess uses equal-weight universe…”（`tracking.py:178`），与 CSI300 主配置不一致  
3. **单一 excess_return** — 无法同时报告 Market Alpha 与 Selection Alpha  
4. **ML 训练**（`config/models.yaml`）target 仍用 `equal_weight_universe`，与研究 attribution benchmark **不一致**  
5. **Progress UI** 标签写「CSI300」但运行时可能是 fallback  

**Fallback 行为（诚实）：** fallback 时 pack 含 `primary: equal_weight_universe`, `fallback_from: csi300_unavailable` — 但未强制前端展示。

---

## 6. 当前 Paper → Outcome 链

**决策：** `canonical_decision.py` → `extract_trading_decisions()`  
**执行：** `services/trading.py` → `execute_picks()` — 优先 `canonical_decisions` where `committee_approve`  
**Outcome：** `tracking.py` → `outcomes_for_report()` — 以 **research_time close** 为 entry  
**Paper 链接：** `execution_tracking.py` → `attach_paper_execution()` — 匹配 symbol 首个 BUY fill ≥ research_time  

**已有字段：** fill price, qty, slippage, `horizons_from_fill`（部分）

**缺口（V5.2 P0）：**

| 字段 | 状态 |
|------|------|
| `decision_id` | 部分（research_id） |
| `snapshot_id` | research_id 别名，未统一命名 |
| `signal_time / order_time / fill_time` | 部分 |
| `market_alpha / selection_alpha` | **不存在** |
| Research outcome vs Paper PnL | **两套**：总览 `/api/pnl` vs `research_outcomes` |
| 无 fill 时 | `execution.available: false`，但不阻断 outcome |

---

## 7. 当前 News → Event → Candidate 链

```
collect_latest(as_of) → filter_asof
    ↓
classify → link_entities → extract_events (rules)
    ↓
ResearchHypothesisEngine.from_event() → FACT/INFERENCE/HYPOTHESIS
    ↓
EvidenceRegistry → E1001…
    ↓
NewsCandidate → CandidateEngine union
    ↓
annotate_news_candidate_price() → price_in_risk (warning only)
```

**能产生 Candidate：** ✅（需 entity link + panel bars + 非 REJECTED）  
**能形成 Event：** ✅（`ExtractedEvent`，规则提取）  
**能形成 Hypothesis：** ✅（规则模板 + `investment_hypothesis` 结构）  
**Price-In：** ✅ 警告层，不 auto-reject  
**Event Lifecycle：** ❌ 仅 `DISCOVERED` / `REJECTED`，无 NEW→PRICED_IN→RESOLVED  
**expected_excess_return：** ❌ 不存在  

**未来函数风险：** `collect_stock()` 在 union 阶段 **未传 as_of**（`candidate/__init__.py:237`）；discovery 主路径有过滤。

---

## 8. Cache 实际命中情况

**实现：** `research/cache.py` — 文件 `{dir}/{hash}.json`，TTL 24h  

**Hash 输入：** symbol, role_id, prompt_version, model, factor/news/model version, as_of, candidate_hash, **完整 role context dict**

**命中条件：** enabled + 文件存在 + 未过期  

**Chairman：** 独立 key（opinion_sig + intel）  

**未覆盖：** Legacy Roundtable（无 ResearchCache）  

**V5.2 问题（审计项 11/19）：**

- Context hash **非 role 专用** — Quant 与 News 字段变化会交叉导致 miss  
- Incremental `NO_CHANGE` 与 Cache **叠加但不等价** — NO_CHANGE 跳过调用；Cache 需 prior 文件  
- **无生产 metrics** 暴露 cache hit rate 到 snapshot（仅 cost tracker 汇总）  
- Fresh symbol / 首次运行：**命中率 ≈ 0**

**估计：** 重复跑同一 as_of + 无变化时，可节省 **40–80%** council calls；首日/新事件 **≈ 0%**。

---

## 9. Dynamic Council 实际调用情况

**实现：** `research/dynamic_council.py` → `plan_council()`  

| Profile | 典型 Roles |
|---------|------------|
| profit_inflection | bear, fundamental, quant |
| major_news | bear, event, (+quant) |
| major_event | bear, event, (+quant) |
| valuation_available | bear, quant, valuation |
| default | bear + 条件 quant |

**Bear：** 几乎总是调用（HIGH_RISK 或 DEFAULT_BEAR）  
**Chairman：** 始终在 `ChairmanEngine` 单独调用  
**Skip：** `skipped_role_opinion()` — 0 LLM，有 skip_reason  

**相对 Full Council（5 roles）：** 典型节省 **1–3 roles/股** → 约 **20–50%** role calls（视 profile）  

**未实现：** Valuation 仅在 `value_available`；News 专用 `news` role（council 无 news role，靠 event）

---

## 10. 二十项审计问答

| # | 问题 | 结论 | 证据 |
|---|------|------|------|
| 1 | 真实交易决策谁产生？ | **Platform Council Chairman** → `build_canonical_decision()` | `council.py`, `canonical_decision.py`, `session.py` |
| 2 | Paper 是否只用 Canonical？ | **是（设计如此）**；fallback 为 committee_verdict / trade_review | `trading.py:execute_picks()` |
| 3 | Legacy Roundtable 仍消耗 LLM？ | **是**，每轮 ~5 calls，`roundtable_mode=benchmark` | `research.py:204–225`, `default.yaml:99–100` |
| 4 | ML 在 Top-N 截断前排序？ | **是** — Union/Research 截断前 `MLRankingEngine.predict_rows()` | `candidate/__init__.py:194–219` |
| 5 | News 能否产生 Candidate？ | **能** — union merge + 过滤 | `opportunity.py`, `candidate/__init__.py` |
| 6 | News 能否形成 Event？ | **能** — 规则 `extract_events()` | `news/extract.py` |
| 7 | Event 能否形成 Hypothesis？ | **能** — `ResearchHypothesisEngine` | `research/hypothesis.py` |
| 8 | ResearchGate 是否减少 LLM？ | **是** — 拒研 0 LLM；tier + budget | `gate.py`, `session.py` |
| 9 | Dynamic Council 是否减少 Role？ | **是** — 非 full 5 roles；Bear 仍常开 | `dynamic_council.py` |
| 10 | ResearchCache 是否真正命中？ | **机制有效**；命中率依赖重复运行，**无 role-specific hash** | `cache.py` |
| 11 | Incremental 是否避免重复？ | **是** — `NO_CHANGE` → 0 role refresh + chair reuse | `incremental.py`, `session.py` |
| 12 | Chairman 是否收到完整 Snapshot？ | **否** — 收到 `build_chairman_context()` 压缩包 | `intel_package.py` |
| 13 | Token Ledger 是否真实 usage？ | **混合** — provider 有则 `actual`，否则 `estimated`；cost 始终估算 | `cost_tracker.py`, `client.py` |
| 14 | Benchmark 是否明确？ | **部分** — resolve 有 primary/fallback；**未入 snapshot**；文案混淆 | `benchmark.py`, `tracking.py:178` |
| 15 | Outcome 与 Paper Fill 连接？ | **部分** — `attach_paper_execution()`；非唯一 PnL truth | `execution_tracking.py` |
| 16 | AI Incremental Alpha 同 universe？ | **topk_ablation 是**；**legacy ai_incremental_alpha 否** | `tracking.py:222–325` |
| 17 | Attribution 区分 Quant/News/Event/Profit/ML？ | **部分** — `discovery_sources` tags；无独立 ML Alpha 层 | `tracking.py:summarize_discovery_sources` |
| 18 | Optimizer 能否改生产参数？ | **默认不能** — `auto_apply: false` | `optimizer_experiment.py`, `default.yaml` |
| 19 | 最大 Token 浪费？ | **Legacy Roundtable 每轮必跑** | 见 §3 |
| 20 | 最大 Alpha 风险？ | **Benchmark 混淆 + 双 metric 误导 + as_of 泄漏缝** | 见 §5、§7 |

---

## 11. P0 / P1 / P2 问题清单（含 Token / Alpha 影响）

### P0 — 必须先做（正确性 + 最大浪费）

| ID | 问题 | Token 节省（估） | Alpha 影响 | 风险 |
|----|------|------------------|------------|------|
| P0-1 | Benchmark 分层 + Snapshot 持久化 + UI 诚实 fallback | 0 | **高** — 否则 Alpha 不可信 | 低 |
| P0-2 | Market Alpha / Selection Alpha 双字段 | 0 | **高** | 低 |
| P0-3 | Roundtable `scheduled`/`sampled`/`disabled` 生产默认 | **−4~5 calls/run (~15–25%)** | 低（已 benchmark_only） | 中 — 需保留 AB 能力 |
| P0-4 | Paper ↔ Outcome 统一 ID 链 + 单一 PnL truth | 0 | **高** | 中 |
| P0-5 | 前端 Benchmark 展示 requested/actual/fallback | 0 | 中（可解释性） | 低 |

### P1 — 降本 + 语义清晰

| ID | 问题 | Token 节省（估） | Alpha 影响 | 风险 |
|----|------|------------------|------------|------|
| P1-1 | Role-specific context hash | **+10–25% cache hit** | 低 | 低 |
| P1-2 | Chairman 仅 role_reports + evidence_ids | **−20–40% chair input tokens** | 中 — 需验证质量 | 中 |
| P1-3 | Evidence registry 注入 title 摘要（非全文） | **−10–30% event role tokens** | 低 | 低 |
| P1-4 | `candidate_score` 语义文档 + prompt 声明 | 0 | **中** — 防 LLM 误读 | 低 |
| P1-5 | `expected_excess_return` 字段（可 available=false） | 0 | **高** — 可验证预测 | 中 |
| P1-6 | Event Lifecycle 状态机 | 0 | **中** — Price-In 特征 | 中 |
| P1-7 | `collect_stock(as_of=)` 全路径 | 0 | **高** — 防泄漏 | 低 |
| P1-8 | ML weight walk-forward 文档化 + 不 auto-apply | 0 | 中 | 低（已实现） |
| P1-9 | LLM budget 扩展（max tokens/cost 硬停） | **可变** | 中 — 可能跳过边缘候选 | 中 |

### P2 — 实验与路由

| ID | 问题 | Token 节省 | Alpha 影响 | 风险 |
|----|------|------------|------------|------|
| P2-1 | 统一 ai_incremental_alpha = topk_ablation | 0 | **高** — _metric 诚实 | 低 |
| P2-2 | Role Ablation 实验框架 | +实验成本 | 高（因果标注 experimental） | 中 |
| P2-3 | Role × Model benchmark | +实验成本 | 中 | 中 |
| P2-4 | Optimizer 强制 experiment gate | 0 | 中 | 低 |

**合计 Token 目标可达性（估）：**

- P0-3 Roundtable 采样：**−15–25% calls**  
- P1 cache + chairman + evidence：**−25–40% tokens/call**  
- 叠加 Gate/Incremental 已有效：**总计 50%+ 可行**，但需 **禁止为了降本跳过 HIGH candidate**

---

## 12. 与 V5 文档对照

| 文档 | 代码符合度 | 主要偏差 |
|------|------------|----------|
| `V5_PHASE0_AUDIT.md` | 部分过时 | V5 已补 Canonical、ML pre-cut、Gate tiers；审计仍有效作历史 |
| `V5_BENCHMARK.md` | 中 | CSI300 已实现；Snapshot 字段、双 Alpha 未实现 |
| `V5_ALPHA_ATTRIBUTION.md` | 中 | topk_ablation ✅；legacy incremental ⚠️；discovery 描述性 |
| `V5_TOKEN_COST.md` | 高 | Ledger 字段齐全；缺 budget 硬 cap、roundtable 采样 |
| `V5_ARCHITECTURE.md` | 中高 | 双栈 Roundtable+Council 仍架构事实 |

---

## 13. 测试覆盖缺口（相对 V5.2 要求）

| 测试 | 状态 |
|------|------|
| Benchmark resolution / fallback | ✅ `test_csi300_execution.py` |
| Market / Selection Alpha | ❌ 未实现字段 |
| Canonical Decision | ✅ `test_decision_consistency.py` |
| Paper Fill → Outcome | ✅ 部分 `test_csi300_execution.py` |
| ML Weight walk-forward | ✅ `test_ml_weight_experiment.py` |
| Research Gate | ✅ `test_research_gate.py` |
| Dynamic Council | 部分 |
| Context Hash (role-specific) | ❌ |
| Incremental NO_CHANGE | ✅ `test_incremental_research.py` |
| Event Lifecycle | ❌ |
| Price-In | 部分 `test_news_phase8.py` |
| Evidence Registry | 部分 |
| AI Incremental (same universe) | 部分 topk |
| Role Ablation / Model routing | ❌ |
| Token Budget | ❌ |
| Optimizer Safety | ✅ `test_phase9_alpha_optimizer.py` |
| Future news rejection | 部分 |

---

## 14. 实施风险（Phase 1+）

1. **降 Roundtable 频率** — 失去每轮 AB 对照；需 `scheduled` 保证可复现实验  
2. **Chairman 压缩过度** — 可能降低 BUY/PASS 质量；需 shadow 对比  
3. **双 Benchmark Alpha** — CSI300 与 EW 同时缺失时须 `available=false`，禁止填 0  
4. **Outcome 统一** — 迁移期 Research vs Paper 口径变化可能影响历史对比  
5. **as_of 收紧** — 可能减少 news 候选数量（正确性 vs 召回）  

---

## 15. Phase 0 结论与下一步

**Phase 0 完成。** 未修改任何业务代码。

**建议 Phase 1 范围（待指令）：**

1. Benchmark pack 写入 snapshot + `market_alpha` / `selection_alpha` 计算  
2. Roundtable `sampled` 模式（如每 10 session 或 daily 1 次）  
3. Paper outcome 统一 schema + 前端 Benchmark 诚实展示  
4. 测试：Benchmark fallback、Market/Selection Alpha、Roundtable 采样  

**禁止在本阶段已开始的事项：**

- 新增 AI Role / Prompt / 新闻源 / 因子  
- Optimizer 自动改生产  
- Dashboard 造假数字  

---

## 附录 A — 关键文件索引

| 主题 | 路径 |
|------|------|
| 研究编排 | `src/ashare/services/research.py` |
| Canonical 决策 | `src/ashare/research/canonical_decision.py` |
| 纸面交易 | `src/ashare/services/trading.py` |
| Benchmark | `src/ashare/research/benchmark.py` |
| Outcome / Alpha | `src/ashare/research/tracking.py` |
| Paper 执行追踪 | `src/ashare/research/execution_tracking.py` |
| Gate | `src/ashare/research/gate.py` |
| Dynamic Council | `src/ashare/research/dynamic_council.py` |
| Cache | `src/ashare/research/cache.py` |
| Incremental | `src/ashare/research/incremental.py` |
| Intel / Chairman | `src/ashare/research/intel_package.py` |
| Cost Ledger | `src/ashare/ai/cost_tracker.py` |
| News Discovery | `src/ashare/news/opportunity.py` |
| Candidate + ML | `src/ashare/candidate/__init__.py`, `src/ashare/ml/candidate_ranking.py` |
| Optimizer | `src/ashare/ai/optimizer_experiment.py` |
| 配置 | `config/research.yaml`, `config/default.yaml` |

---

*End of V5.2 Phase 0 Audit. Phases 1–5 implemented 2026-08-22 — see `docs/V5_2_COMPLETE.md`.*
