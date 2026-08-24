# V5.4 Phase 0 Audit — Alpha Lab + Adaptive AI Routing

**Project:** 寻龙尺 (XunLongChi) · Python 包名 `ashare`  
**Audit date:** 2026-08-24  
**Trusted baseline (V5.3):** `e62e2e9b4dba42c8b6e0fe7a462d31648c93fa7a`  
**Audit HEAD (read-only):** `994573e` — 含早期 V5.4 部分实现 + 品牌更名 + 卖出通知  
**Phase scope:** **Phase 0 only** — 本文档；**未修改任何业务代码**

---

## 0. Executive Summary

V5.3 @ `e62e2e9` 已建立 **Canonical Decision → RiskFilter → Notification → Outcome** 主链，以及 LLM Budget、Research Cache、Dynamic Council、Paper Fill、Outcome Truth。

当前仓库在 `e62e2e9` 之上已有 **部分 V5.4 Alpha Validation 实现**（commit `ed55ced`），但与本版规格 **「Alpha Lab + Adaptive AI Routing」** 相比：

| 领域 | 已有（可复用） | 本版仍缺 |
|------|----------------|----------|
| 统一 Attribution 记录 | ⚠️ 分散在 outcome / snapshot / notification | 单条 Candidate 归因 schema + `candidate_id` |
| Primary / Secondary Source | ✅ `signal_attribution.resolve_primary_source()` + config | ⚠️ 与 Outcome Truth 字段名冲突；News Discovery vs Evidence 未分离 |
| Alpha Lab API / UI | ✅ `/api/alpha-lab` + `AlphaLab.tsx`（极简） | Source 表完整列、Routing、Token Efficiency、滚动窗口、程序结论 |
| AI Ablation | ✅ `ai_ablation.run_council_ablation()` | 与 V5.2 Top-K 指标并存需统一；负 Alpha 显式标签 |
| ML Ablation | ⚠️ `ml/weight_experiment.py` 独立实验 | 未接入 attribution_report / Alpha Lab |
| Prediction Calibration | ✅ `calibration.build_calibration()` | minimum_sample=30；median/win_rate 分桶不全 |
| Price Truth | ✅ `price_truth.py` + notification metadata | Research outcome 缺显式 `notification_price` 列 |
| Adaptive AI Routing | ❌ **完全不存在** | conflict_score、LOW/MEDIUM/HIGH、Routing Outcome、Token Savings |
| Sample Size 门槛 | ⚠️ `minimum_sample: 5` | 规格要求默认 **30** + INSUFFICIENT_SAMPLE 禁结论 |
| 时间窗口 | ❌ | 7D / 30D / 90D / All Time |
| 测试 | ⚠️ `tests/test_v5_4_*.py`（17 项） | 规格 `test_v54_*` + Routing / Token Efficiency |

**核心原则（审计确认）：** Measurement > Features · Incremental Alpha > Absolute Score · Alpha/Cost > Token Count · **禁止**重复实现 V5.3 已有 Notification / Outcome Truth / LLM Budget。

**本版第二核心（Adaptive AI Routing）在代码中零实现** — 这是最重大缺口。

---

## 1. 当前 Alpha 数据在哪里产生？

### 1.1 Research Signal Alpha（研究信号 → 收益）

| 模块 | 路径 | 函数 | 输出 |
|------|------|------|------|
| Horizon 计算 | `src/ashare/research/tracking.py` | `TrackingEngine.outcomes_for_report()` L56–118 | `horizons.{1,3,5,10,20,60}`：`actual_return`, `market_alpha`, `selection_alpha` |
| 双 Benchmark | `src/ashare/research/benchmark.py` | `resolve_dual_benchmark_pack()` | CSI300 + equal-weight universe 超额 |
| Outcome Truth | `src/ashare/research/outcome_truth.py` | `apply_primary_truth()` | `primary_horizons`（paper_fill > signal_close） |
| Paper Fill Alpha | `src/ashare/research/execution_tracking.py` | `attach_paper_execution()` | `execution.horizons_from_fill` |
| 聚合报告 | `src/ashare/research/tracking.py` | `ReviewEngine.attribution_report()` L218–308 | `research_outcomes` pack |

**Entry 价格规则：**

- Research outcome：`signal_time` 当日 close → `signal_price`（L89–118 tracking）
- Paper：`execution.fill_price` → `paper_fill_price`（price_truth + execution_tracking）
- Notification：`notify_price` @ 发送时刻（notification/outcome.py）

### 1.2 Discovery / Source Alpha

| 模块 | 路径 | 说明 |
|------|------|------|
| 按 tag 描述统计 | `tracking.py` | `summarize_by_source()` L147 — **参与 tag**，非 primary discovery |
| Primary source 统计 | `research/signal_attribution.py` | `summarize_signal_attribution()` — `by_primary_source` |
| Cohort 对比 | `signal_attribution.py` | `cohort_compare()` — news/event with vs without tag |
| Factor IC | `research/factor_attribution.py` | 复用 `factors/ic.py`；advisory RETIRE_CANDIDATE |

### 1.3 AI Incremental Alpha

| 模块 | 路径 | 方法 |
|------|------|------|
| Canonical Top-K | `tracking.py` | `compute_topk_ablation_alpha()` L310+ — quant score vs chairman rating |
| Legacy | `tracking.py` | `compute_ai_incremental_alpha()` L400+ — source_bucket 分组 |
| V5.4 Council Ablation | `research/ai_ablation.py` | `run_council_ablation()` — 同 universe Top-K，0 额外 LLM |

### 1.4 Notification Alpha

| 模块 | 路径 | 说明 |
|------|------|------|
| Outcome seed | `notification/outcome.py` | `seed_notification_outcome()` — 仅 `status=SENT` 后写入 |
| Refresh | `notification/outcome.py` | `refresh_notification_outcomes()` — entry=`notify_price` |
| Discovery attr | `notification/outcome.py` | `compute_discovery_attribution()` — 按 notification candidate_sources |

### 1.5 Alpha Lab 聚合

| 模块 | 路径 | 说明 |
|------|------|------|
| 编排 | `services/alpha_lab.py` | `build_alpha_lab()` — 读 `latest_research()` pack |
| API | `api/app.py` | `GET /api/alpha-lab` |

---

## 2. 当前 Outcome 在哪里产生？

```
run_research()  [services/research.py]
  → platform_reports (ResearchSessionEngine.run_pool)
  → ReviewEngine.attribution_report(reports, panel)
       → outcomes_for_report() × N
       → attach_paper_execution()
       → apply_primary_truth()
       → enrich_outcome_sources()
       → attach_signal_price / attach_paper_fill_price
       → persist_outcomes() → data/research_outcomes.jsonl
  → schedule_notification_job() [async]
       → seed_notification_outcome() [仅 SENT]
       → data/notifications/notification_outcomes.jsonl
```

**持久化：**

- Research outcomes：`ReviewEngine.persist_outcomes()` → `data/research_outcomes.jsonl`
- Notification outcomes：`NotificationStore.outcome_path`
- Production cycles：`data/production_cycles.jsonl`（`notification/production.py`）

**Horizon 配置：**

- Research tracking：`config/research.yaml` → `tracking.horizons_days: [1,3,5,10,20,60]`
- Attribution 展示：`attribution.horizons_days: [1,5,10,20]`
- Notification：`notification.yaml` → `outcome.horizons_days: [1,5,10,20]`

---

## 3. 当前 candidate_sources 如何保存？

### 3.1 产生

| 阶段 | 文件 | 逻辑 |
|------|------|------|
| Pool 候选 | `candidate/__init__.py` | `_pool_discovery_sources()` L14–35 → `quant` / `event` / `profit` |
| News union | `candidate/__init__.py` | L162+ union 时 append `news` |
| ML 参与 | `session.py` | `ml_prediction` 写入 snapshot.quant，**不写入 candidate_sources** |
| AI 参与 | `session.py` | council/chairman 输出，**不写入 candidate_sources** |

### 3.2 传播链

```
candidate["candidate_sources"]
  → snapshot.py L104
  → session report L84
  → canonical_decision L90 (via research.py)
  → tracking outcome L72-73
  → notification metadata (service.py L186)
  → notification outcome (outcome.py L44-45)
```

### 3.3 Primary / Secondary（V5.4 部分已有）

- **配置：** `config/research.yaml` → `attribution.primary_source_priority: [profit, event, quant, news, ml]`
- **解析：** `signal_attribution.resolve_primary_source()` — 按 priority 取第一个命中为 primary，其余 secondary
- ** enrich：** `enrich_outcome_sources()` 在 attribution_report 末尾调用

### 3.4 缺口（相对本版规格）

1. **`ml` / `ai` 从未进入 candidate_sources** — 无法作为 discovery source 统计
2. **`by_tag` 与 `by_primary_source` 并存** — `summarize_signal_attribution.by_tag` 仍按「参与研究」计数，易与 Discovery 混淆
3. **News Discovery vs News Evidence 未分离** — `cohort_compare(tag="news")` 用的是 `candidate_sources` 含 news，而非 `primary_source==news` vs `news in secondary_sources`
4. **无 `candidate_id`** — 仅有 `symbol + research_session_id`

---

## 4. 当前 AI Incremental Alpha 如何计算？

### 4.1 Canonical（V5.2，仍在用）

`tracking.compute_topk_ablation_alpha()`:

- **A（baseline）：** Top-K by `candidate_score` / quant factor_score
- **B（with AI）：** Top-K by chairman `research_rating` 权重 + confidence
- **Δα：** B 组 mean(selection_alpha) − A 组 mean(selection_alpha) @ horizon（默认 T+5）
- **数据源：** `primary_horizons` only（via `_primary_cell`）

### 4.2 V5.4 Council Ablation（新增，可复用）

`ai_ablation.run_council_ablation()`:

- 与 Top-K 逻辑等价但更完整：T+1/5/10/20、median、win_rate、std
- 附加 `ai_efficiency = incremental_alpha_T5 / llm_cost_usd`
- `status`: STRONG / WEAK / INEFFICIENT / UNPROVEN
- **0 额外 LLM** — 回放 persisted reports

### 4.3 Legacy（仍返回，勿删）

`compute_ai_incremental_alpha()` — 按 `source_bucket`（news_only / quant_only / news_plus_quant）分组，与「Council on/off」实验不同。

### 4.4 缺口

- 未显式标注 **NEGATIVE_INCREMENTAL_ALPHA**
- `attribution_report` 同时返回三套指标，Alpha Lab 需统一展示口径
- 无 **按 routing_level** 分组（Routing 未实现）

---

## 5. 当前 Notification Outcome 如何计算？

| 步骤 | 模块 | 规则 |
|------|------|------|
| Gate | `notification/gate.py` | BUY / STRONG_BUY / RATING_EXIT / RISK_EXIT；0 LLM |
| 发送成功 | `notification/service.py` | `status=SENT` 后 `seed_notification_outcome()` |
| Entry | `notification/outcome.py` | `entry_type=notify_price`；metadata.notify_price |
| Refresh | `refresh_notification_outcomes()` | 从 notify_time 后 T+h close 算 return / market_alpha / selection_alpha |
| 归因 | `compute_notification_attribution()` | 按 level：BUY, STRONG_BUY, RATING_EXIT, RISK_EXIT |

**严格规则（已遵守）：**

- 发送失败 / SKIPPED / COOLDOWN → **不** seed outcome（service.py 仅在成功发送路径 seed）
- Notification alpha **独立**于 research signal close

**缺口：**

- outcome 行缺显式 `notification_price` 顶层字段（在 metadata 内）
- Discovery attribution 仍用 candidate_sources tag，非 primary_source

---

## 6. 当前 LLM cost 如何记录？

| 模块 | 路径 | 说明 |
|------|------|------|
| Ledger | `ai/cost_tracker.py` | `AICostTracker` → `data/ai/usage.jsonl` |
| 字段 | `LLMUsageRecord` | request_id, cycle_id, research_session_id, symbol, role, model, input/output tokens, estimated_cost_usd, cache_hit |
| Client hook | `ai/client.py` | `_record_usage()` |
| Cycle rollup | `cost_tracker.cycle_summary()` | n_calls, tokens, estimated_usd, cache_hit_rate |
| Budget | `research/llm_budget.py` | max_calls / tokens / cost_usd vs used；hard_stop |
| Model benchmark | `research/model_benchmark.py` | 按 model/role 汇总；`alpha_per_100k_tokens`（非 incremental） |

**传播：**

- `research.py` → payload `ai_cost`
- `ai_ablation` ← `get_cost_tracker().cycle_summary().estimated_usd`
- `production.py` → `production_cycles.jsonl`

**缺口：**

- 无 **V5.3 baseline vs V5.4 routing** 对比存储
- 无 per-candidate routing 级 cost 分摊

---

## 7. 当前 Research Session 如何关联？

| 标识 | 格式 | 产生 | 关联 |
|------|------|------|------|
| `research_session_id` | `R{YYYYMMDD}{6-hex}` | `snapshot.py` L68 | = research_id = snapshot_id |
| Gate skip | `G{YYYYMMDD}{6-hex}` | `session.py` | 无 council |
| Canonical | `canonical_decision.py` | `research_session_id`, `snapshot_id` | |
| Outcome | `tracking.outcomes_for_report` | research_id, snapshot_id, decision_id | |
| LLM usage | `cost_tracker` | research_session_id, symbol | |
| Notification | `notification/store.py` | decision_id, research_session_id, snapshot_id | |
| Index | `data/research_sessions.jsonl` | session._append_index | |

**缺口：** 无统一 **candidate_id** 跨 cycle 追踪同一 symbol 多次研究。

---

## 8. 当前 Snapshot 如何关联？

- **路径：** `data/research_snapshots/{research_id}.json`
- **Latest：** `data/research_snapshots/_latest_{symbol}.json`
- **内容：** quant/profit/event/market/council/chairman/candidate_sources/candidate_score_meta/news_package/research_intelligence
- **读取：** Notification service `_load_snapshot(cfg, research_id)`；Incremental research 读 prior snapshot

**expected_excess_return 在 snapshot：** `candidate_score_meta.expected_excess_return`（多数 `available=false`）

---

## 9. 当前哪些字段存在 available=false？

| 字段 / 块 | 位置 | 条件 |
|-----------|------|------|
| `expected_excess_return` | snapshot, hypothesis | 无可靠 expectation_gap |
| `profit_inflection.available` | profit engine | 缺 as-of 财务序列；仅预告 meta |
| `profit_inflection` quality D | profit | 负面预告 / 一次性收益 |
| `execution.available` | execution_tracking | 无 paper fill / 无 research_time |
| `price_reaction.available` | price_reaction, news | 缺 bars |
| `value_available` / `quality_available` | snapshot | 估值/质量因子未算 |
| `news_discovery.available` | research.py | 未跑 news 阶段 |
| `factor_attribution.available` | factor_attribution | 无 factor panel |
| `ai_council_ablation.available` | ai_ablation | eligible symbols < 2 |
| `calibration` EER buckets | calibration | sample < minimum_sample |
| `portfolio_attribution.available` | outcome_truth | 无 primary horizon returns |
| `intel_package` 多块 | intel_package.py | industry_map, historical_event_outcomes 等 |

**规则（已遵守）：** 不可用时不填假数值；Notification Gate 对 EER unavailable 直接 SKIP BUY。

---

## 10. 当前哪些地方可能存在 future leakage？

| 风险点 | 严重性 | 说明 |
|--------|--------|------|
| Research outcome entry | ✅ 低 | `as_of` 当日 close；future bars 仅用于 T+h |
| Notification outcome | ✅ 低 | notify_time 之后 bars |
| Paper fill | ✅ 低 | fill_time 之后 horizons |
| Benchmark pack | ⚠️ 中 | `benchmark.resolve_dual_benchmark_pack(as_of)` — 需确认 as_of 不含未来 |
| ML training | ⚠️ 中 | `ml/leakage.py` 存在；weight_experiment 用 walk_forward — 与 live research 分离 |
| Top-K ablation | ⚠️ 中 | 同 as_of universe 上比较排序 — 若 universe 含事后才知道的赢家，有 survival bias |
| `by_tag` discovery | ⚠️ 中 | 把 research 阶段参与的 tag 当 discovery，**概念泄漏**（非价格未来函数） |
| primary_source 覆写 | 🔴 高 | 见 §11 — 字段语义冲突可能导致错误解读 |
| Alpha Lab 读 latest only | ⚠️ 中 | 无 time split；全样本混合 |

**T+1 成交规则（workspace rule）：** 回测/纸面默认 signal T → fill T+1；tracking 用 close@signal_day 作 research entry，与 paper fill 分轨 — **符合设计**，但需在统一 schema 标明 `entry_type`。

---

## 11. 当前最适合增加 Alpha Lab 的位置？

### 11.1 后端编排（推荐扩展点）

**Primary：** `src/ashare/services/alpha_lab.py` — 已是聚合层；应扩展为：

- 读 **historical** outcomes（非仅 `latest_research()`）
- 调用已有 `signal_attribution`, `ai_ablation`, `calibration`, `factor_attribution`
- 新增：`news_discovery_alpha`, `news_evidence_alpha`, `ml_ablation`, `token_efficiency`, `programmatic_summary`

**Secondary：** `src/ashare/research/tracking.py` → `attribution_report()` — 产出 raw outcomes；**不要**重复算 horizon

**Unified schema 插入点：** 在 `attribution_report()` 返回前，或新模块 `research/unified_attribution.py`，将每条 outcome enrich 为 Phase 1 字段表

### 11.2 API

- 已有 `GET /api/alpha-lab` — 扩展 query：`window=7d|30d|90d|all`
- 可选：`GET /api/alpha-lab/source/{source}` — 非必须

### 11.3 前端

- 已有 `web/src/pages/AlphaLab.tsx` — 仅单表；扩展为 6 区块（Source / Ablation / Calibration / Routing / Token / Summary）
- 路由已在 `App.tsx` `/alpha-lab`

### 11.4 🔴 必须修复的设计冲突

`outcome_truth.apply_primary_truth()` 将 **`primary_source`** 设为 `paper_fill | signal_close`（entry 类型）。

随后 `enrich_outcome_sources()` **覆写** `primary_source` 为 discovery source（event/news/…）。

**影响：** Outcome Truth 语义丢失；Alpha Lab 若读 outcome.primary_source 得到的是 discovery 而非 entry rule。

**建议（Phase 1）：** 重命名 entry 字段为 `primary_entry_source` 或 `outcome_entry_type`；discovery 用 `discovery_primary_source`。**本审计仅记录，未改代码。**

---

## 12. 当前最适合增加 AI Routing 的位置？

### 12.1 现状：无 Routing

- 全仓库 **零匹配** `ai_routing`, `routing_level`, `routing_score`, `conflict_score`
- Council 调用：`ResearchSessionEngine.run_session()` → **每个进 pool 的候选都跑** `council.run_parallel()`（受 research_gate tier 影响但未按 conflict 路由）
- `dynamic_council.py` — 按 profile 选 **角色子集**，不是 Skip/Light/Full Council
- `research/gate.py` — LLM **前**漏斗（DEEP/LIGHT/NO_RESEARCH），基于 candidate_score 阈值，**非 conflict score**

### 12.2 推荐插入点

```
CandidateEngine.build_research_universe()
  ↓
apply_research_gate()          [已有 — tier]
  ↓
★ compute_ai_routing_score()  [新增 — 0 LLM]
  ↓
route_council(candidates)     [新增 — LOW skip / MEDIUM light / HIGH full]
  ↓
ResearchSessionEngine.run_pool() [改 — 按 routing 决定是否 call council]
  ↓
persist routing outcome       [新增 — snapshot + cost_tracker 关联]
```

**配置建议：** `config/research.yaml` 新增 `ai_routing:` 段（thresholds、weights），与 `llm_budget` 并列。

**轻量 Research 预留：** `CouncilPlan` / `run_session(skip_council=True, routing_level=...)` 接口。

### 12.3 Token Savings 对比

- **Baseline 存储：** 每 cycle 已有 `production_cycles.jsonl` + `ai/usage.jsonl` — 可 replay V5.3「全 Council」假设 vs 实际 routing
- **指标计算：** 新模块 `research/token_efficiency.py` 或在 `alpha_lab.py` 中读两 cycle 汇总

---

## 13. 本版规格 vs 现有实现 — Phase 映射

| Phase | 主题 | 状态 | 复用建议 |
|-------|------|------|----------|
| 0 | Audit | ✅ 本文档 | — |
| 1 | Unified Attribution | ⚠️ 部分 | 扩展 outcome enrich；修 primary_source 命名 |
| 2 | Discovery Attribution | ⚠️ 部分 | 用 `by_primary_source`；弃用 by_tag 作 Discovery |
| 3 | Primary Source 规则 | ✅ | `config/research.yaml` + `resolve_primary_source` |
| 4–5 | Alpha Lab 表 | ⚠️ 骨架 | 扩展 `alpha_lab.py` + UI |
| 6 | minimum_sample=30 | ❌ | 现为 5；需新 key `minimum_sample_size` |
| 7 | 统计量 | ⚠️ 部分 | signal_attribution 有 mean/median/win_rate/std |
| 8 | News Discovery Alpha | ❌ | 需 primary==news cohort |
| 9 | News Evidence Alpha | ❌ | 需 secondary contains news cohort |
| 10 | Event Alpha | ⚠️ | cohort_compare event — 需改为 primary |
| 11 | Profit Alpha | ⚠️ | profit 常 available=false → DATA_UNAVAILABLE |
| 12 | Quant Alpha | ⚠️ | factor_attribution + primary quant |
| 13 | ML Ablation | ⚠️ | 复用 weight_experiment，接入 pack |
| 14–16 | AI Ablation / Efficiency | ✅ 大部分 | `ai_ablation.py` |
| 17 | 负 Alpha 显式 | ❌ | 加 NEGATIVE_INCREMENTAL_ALPHA 标签 |
| 18–20 | Calibration | ✅ 大部分 | `calibration.py`；补 median return |
| 21 | Price Truth | ✅ 大部分 | `price_truth.py`；统一字段名 |
| 22–30 | Adaptive AI Routing | ❌ | **全新** |
| 31–32 | Token Savings / Retention | ❌ | **全新** |
| 33 | 不做 Portfolio/QMT | ✅ | 未实现 |
| 34–37 | 前端 6 区块 | ⚠️ 1/6 | 扩展 AlphaLab.tsx |
| 38 | 程序结论 | ❌ | template from stats |
| 39–40 | 禁过拟合 / Time Split | ❌ | 观察 only + window filter |
| 41 | 滚动 7D/30D/90D | ❌ | |
| 42 | test_v54_* | ⚠️ |  rename/extend from test_v5_4_* |
| 43 | 安全 | ✅ | Alpha Lab / Routing 无 broker 调用 |
| 44 | 12 问 | ⚠️ | 见 §14 |
| 45–46 | 禁止新 Feature / 顺序 | — | 按 Phase 1 起实施 |

---

## 14. V5.4 最终十二问 — 当前能否回答？

| # | 问题 | 现能否回答 | 依据 / 缺口 |
|---|------|------------|-------------|
| 1 | Event 有没有 Alpha？ | ⚠️ 部分 | `by_primary_source.event` + cohort_compare；样本少时 INSUFFICIENT；entry 字段冲突 |
| 2 | Profit Inflection 有没有 Alpha？ | ⚠️ 部分 | 多票 `profit_inflection.available=false` → 需 DATA_UNAVAILABLE |
| 3 | Quant 有没有 Alpha？ | ⚠️ 部分 | primary quant + factor IC |
| 4 | News **Discovery** Alpha？ | ❌ | 未按 primary==news 隔离 |
| 5 | News **Evidence** 价值？ | ❌ | 未按 secondary 含 news 且 primary!=news |
| 6 | ML Incremental Alpha？ | ❌ | weight_experiment 未接入 |
| 7 | AI Council Incremental Alpha？ | ✅ | ai_ablation + topk |
| 8 | AI 最适合哪类股票？ | ❌ | 无 Routing outcome |
| 9 | Adaptive Routing 省多少 Token？ | ❌ | Routing 不存在 |
| 10 | Alpha 有没有保持？ | ❌ | 无 Alpha Retention 指标 |
| 11 | expected_excess_return 校准？ | ⚠️ 部分 | calibration.eer_calibration；EER 多 unavailable |
| 12 | confidence 校准？ | ⚠️ 部分 | confidence_calibration 分桶 |

---

## 15. 已有测试与文档（避免重复）

| 资产 | 路径 |
|------|------|
| V5.4 测试 | `tests/test_v5_4_attribution.py`, `_ablation.py`, `_calibration.py`, `_notification_truth.py`, `_alpha_efficiency.py` |
| 旧审计 | `docs/V5_4_ALPHA_VALIDATION_AUDIT.md`, `docs/V5_4_COMPLETE.md` |
| V5.3 测试 | `tests/test_v5_3_notification.py`（含 RATING_EXIT） |

**注意：** 旧 V5.4 文档基于「Alpha Validation」口径；本版追加 **Adaptive AI Routing** 与 **minimum_sample=30**，以本文档为准。

---

## 16. Phase 0 结论与 Phase 1 建议

### 16.1 必须复用（禁止重写）

- Outcome Truth / Paper Fill / Benchmark / Notification Gate & Outcome
- LLM Budget + Cost Tracker + Research Cache + Dynamic Council
- `signal_attribution`, `ai_ablation`, `calibration`, `price_truth`, `factor_attribution`
- `/api/alpha-lab` + `AlphaLab.tsx` 骨架

### 16.2 Phase 1 优先事项

1. **修复 `primary_source` 语义冲突** — entry vs discovery 分列
2. **Unified attribution row** — Phase 1 字段表 + `available=false` 契约
3. **News Discovery / Evidence 双 cohort** — 基于 primary/secondary，非 by_tag
4. **`minimum_sample_size: 30`** — 与 INSUFFICIENT_SAMPLE 禁 STRONG/WEAK 结论
5. **Historical outcomes 读取** — Alpha Lab 支持 7D/30D/90D/all

### 16.3 Phase 5 优先事项（Routing）

1. `research/ai_routing.py` — 0 LLM conflict_score + LOW/MEDIUM/HIGH
2. 接入 `session.run_pool` — LOW skip council
3. Routing outcome 持久化 + Token Savings vs baseline

---

**Phase 0 完成。下一步：Phase 1 Unified Attribution（按 §16.2 顺序），每 Phase 后 `pytest tests/ -q`。**
