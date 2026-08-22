# V5.4 Phase 0 Audit — Alpha Validation & Ablation Framework

**Project:** [LongTan Radar](https://github.com/Skeiro666/LongTanRadar)  
**Audit date:** 2026-08-22  
**Code baseline:** `main` @ `e62e2e9` (V5.3 Notification & Production Validation)  
**Phase:** 0 audit + **V5.4 implementation complete (2026-08-22)**  
**Rule:** Code is authoritative; V5.2/V5.3 已实现模块勿重复造轮子。

---

## 0. Executive Summary

LongTanRadar 已从 **Feature Engineering** 进入可度量阶段：V5.2 建立了双 Benchmark、Outcome Truth、Top-K AI incremental alpha；V5.3 建立了 Notification outcome 与 Production cycle 记录。

**V5.4 核心缺口：** 尚无统一的 **Ablation Framework**、**Prediction Calibration**、**Primary Source 规则**、**Alpha Lab 前端**，以及 **AI Efficiency（Incremental Alpha / LLM Cost）** 的一等公民指标。

| 领域 | V5.2/V5.3 现状 | V5.4 仍缺 |
|------|----------------|-----------|
| Signal / Discovery Attribution | ⚠️ 描述性 `discovery_attribution`（mean_return） | T+1/5/10/20 **market/selection α** 按 tag；`primary_source` |
| AI Ablation | ⚠️ Top-K heuristic replay（非 No-AI vs With-AI 实验） | 实验 A/B：Council on/off，同 universe |
| Calibration | ❌ | EER / confidence vs realized α；bias；分桶 hit rate |
| Price Truth | ⚠️ 三轨并存 | 显式 `signal_price` / `notify_price` / `paper_fill_price` 字段 + 禁止混读 |
| Factor IC | ⚠️ `factors/ic.py` 存在 | 未接入 research cycle；无 RETIRE_CANDIDATE |
| Alpha Lab UI | ❌ | 统一 Module × Samples × α × Cost × Efficiency |
| AI Efficiency | ⚠️ `alpha_per_100k_tokens`（model_benchmark） | `AI Efficiency = Δα / LLM Cost` 多 horizon |

**V5.4 原则（审计确认）：** Measurement > Features · Evidence > Opinion · Incremental Alpha > Absolute Score · **禁止**新增 AI 角色/新闻源/模型/交易策略。

---

## 1. 当前 Alpha 数据流

```
CandidateEngine.build_research_universe()
    candidate_sources ← _pool_discovery_sources() + news union
    ↓
ResearchSessionEngine → snapshot + council
    expected_excess_return ← hypothesis (多数 available=false)
    confidence ← chairman
    ↓
build_canonical_decisions() + RiskFilterEngine
    research_rating · trading_action · risk_status
    ↓
ReviewEngine.attribution_report()
    horizons @ signal_close (research_time)
    attach_paper_execution() → paper_fill horizons
    apply_primary_truth() → primary_horizons (paper_fill > signal_close)
    ai_incremental_alpha (Top-K ablation)
    discovery_attribution (tag mean_return)
    ↓
[V5.3] schedule_notification_job()
    notify_price @ send time → notification outcome (isolated store)
    ↓
record_production_cycle() → data/production_cycles.jsonl
```

---

## 2. 关键字段审计

### 2.1 `candidate_sources`

| 项 | 详情 |
|----|------|
| **写入** | `candidate/__init__.py` `_pool_discovery_sources()` L14–35 |
| **标签** | `quant`, `event`, `profit`（池）；`news`（Discovery union L162） |
| **传播** | snapshot L104 → session L84 → canonical L90 → outcomes L46–54 → notification metadata L185 |
| **缺失** | **`ml`、`ai` 从未写入 candidate**；仅在 `tracking.summarize_discovery_sources()` 的 tag 列表中出现 |
| **多标签** | 允许同时存在（如 `["event","quant","profit"]`） |

**V5.4 要求：** 区分 **primary_source** vs **secondary_sources** — **当前不存在**。所有 tag 平等参与 discovery attribution，无法回答「最初是谁发现的」。

### 2.2 `expected_excess_return`

| 项 | 详情 |
|----|------|
| **生成** | `research/hypothesis.py` `to_investment_hypothesis()` L112–143 |
| **默认** | `available=false`（无 expectation_gap 不伪造） |
| **快照** | `snapshot.py` `_candidate_score_meta()` L18–34 |
| **消费** | V5.3 Notification Gate 硬门槛（不可用则 SKIP BUY） |

**V5.4 Calibration 基础数据存在但未闭环：** 有 predicted EER 字段，**无** realized EER 对比、bias、分桶校准表。

### 2.3 `confidence`

| 项 | 详情 |
|----|------|
| **来源** | Chairman LLM / heuristic（`council.py` fallback 0.45） |
| **Canonical** | `canonical_decision.py` L85, L99 |
| **Gate** | Notification BUY≥0.65, STRONG_BUY≥0.75 |

**无** confidence calibration（分桶 hit rate vs T+5/T+10）。

### 2.4 `research_rating` / `trading_action`

| 项 | 详情 |
|----|------|
| **Canonical** | `canonical_decision.py` L51–52, L79–80 |
| **分离** | `config/research.yaml` `separate_trading_action: true` |
| **Approve** | `SMALL_POSITION` + BUY/STRONG_BUY + gate + risk pass |

Outcome `by_rating` 统计在 `tracking.summarize_by_rating()` L108–125。

### 2.5 `market_alpha` / `selection_alpha`

| 项 | 详情 |
|----|------|
| **计算** | `tracking.py` `outcomes_for_report()` L84–92 |
| **Benchmark** | `benchmark.py` `resolve_dual_benchmark_pack()` — CSI300 + EW |
| **Truth** | `outcome_truth.py` — `primary_horizons` 优先 paper fill |
| **Legacy** | 单字段 `excess_return`（market 优先 fallback）仍并存 |

Research path 使用 **`actual_return`**；Notification path 使用 **`realized_return`** — 命名不一致。

### 2.6 `ai_incremental_alpha`

| 实现 | 文件 | 方法 | 说明 |
|------|------|------|------|
| **Canonical** | `tracking.py` L264–362 | `compute_topk_ablation_alpha()` | 同 universe Top-K：baseline `candidate_score` vs AI rating+confidence |
| **Legacy** | `tracking.py` L364–418 | `compute_ai_incremental_alpha()` | quant_only bucket vs council_reviewed cohort |
| **Experimental** | `role_ablation.py` | `compute_role_ablation()` | 合成 chair 分数，**非** LLM 重跑 |

**与 V5.4 规格差距：**

- 现有 Top-K ablation **不是**「No AI Council vs With AI Council」实验
- 使用 `horizons` 而非 `primary_horizons`（忽略 paper fill truth）
- `ranking_method=heuristic_rating_to_score` — 非真实 Council off/on
- `config/research.yaml` `ab_test` **未接线**（`quant_only_key` / `quant_ai_key`）

### 2.7 Notification Outcome

| 项 | 详情 |
|----|------|
| **模块** | `notification/outcome.py` |
| **Entry** | `notify_price`（`service.py` `_notify_price()` snapshot close） |
| **Horizons** | T+1/5/10/20；`market_alpha` / `selection_alpha` |
| **Attribution** | `compute_notification_attribution()` by BUY/STRONG_BUY/RISK_EXIT |
| **Discovery** | `compute_discovery_attribution()` on notification outcomes |
| **存储** | `data/notifications/outcomes.jsonl`（与 research outcomes **分离**） |

**缺失字段（V5.4 §17）：** `decision`, `confidence`, `expected_excess_return`, `primary_source` 未写入 notification outcome seed。

---

## 3. Primary Source — 当前不存在

### V5.4 规格

```
primary_source = event
secondary_sources = [quant, news, ml]
```

配置化优先级：

```yaml
attribution:
  primary_source_priority: [profit, event, quant, news, ml]
```

### 当前行为

- `candidate_sources` 为 **flat list**，无 primary/secondary 区分
- `_pool_discovery_sources()` 可同时打多个 tag，**无优先级消解**
- `tracking._source_bucket()` 仅分 `news_only` | `quant_only` | `news_plus_quant`

**Phase 1 必须新增：** `resolve_primary_source(sources, priority_config) → {primary, secondary}`，写入 outcome / notification outcome / Alpha Lab。

---

## 4. AI Ablation — 现有 vs 所需

### V5.4 规格

| 实验 | 条件 |
|------|------|
| **A — No AI Council** | Quant + Event + Profit + News + ML；**不调用 Council** |
| **B — With AI Council** | 同上 + Council |
| **比较** | T+1/5/10/20 Market α & Selection α |
| **指标** | AI Incremental Alpha = B − A；mean/median/win rate/std；INSUFFICIENT_SAMPLE |

### 现有能力（可复用，勿重写）

| 模块 | 可复用点 |
|------|----------|
| `tracking.compute_topk_ablation_alpha()` | 同 universe 排名对比框架 |
| `ml/weight_experiment.py` | Walk-forward、Top-K metrics、max_drawdown |
| `role_ablation.py` | 角色 drop 实验模式（需标注 experimental） |
| `model_benchmark.py` | Token/cost rollup |

### 缺口

1. **无「Council off」实验路径** — `ResearchSessionEngine.run_session()` 始终调用 `AICouncilEngine`
2. **无离线 replay store** — 无法对历史 snapshot 批量跑 A/B
3. **Top-K ablation ≠ Council ablation** — 仅改 ranking heuristic，未移除 AI 链路
4. **`ab_test` config 未使用**
5. **role_ablation 未读 `primary_horizons`**

**Phase 2 建议：** 新增 `research/ai_ablation.py`（或 `alpha/ablation.py`），基于 persisted snapshot 做：
- A：deterministic score-only decision（Gate + quant score，0 LLM）
- B：actual council report from snapshot
- 共用同一 outcome panel + benchmark pack

---

## 5. Prediction Calibration — 完全缺失

### V5.4 规格

| 类型 | 分桶 | 输出 |
|------|------|------|
| EER calibration | 0–2%, 2–5%, 5–10%, 10%+ | predicted vs realized mean；bias |
| Confidence calibration | 0.50–0.60 … 0.90–1.00 | T+5/T+10 hit rate |

### 当前

- `expected_excess_return` 多数 `available=false` → 校准样本可能极少（诚实展示 INSUFFICIENT_SAMPLE）
- Outcome horizons 在 research path 可用；需按 **primary_horizons** 取 realized
- **无** `predicted_excess_return` / `realized_excess_return` 持久化对

**Phase 3 建议：** 新增 `research/calibration.py`，输入 outcomes + platform_reports，输出 calibration buckets；API + Alpha Lab 展示。

---

## 6. Price Truth — 三轨分离（部分实现）

| 概念 | 当前实现 | 字段名 | V5.4 要求 |
|------|----------|--------|-----------|
| **Signal price** | `tracking.py` L69 signal-day close | 隐式（无 `signal_price` 字段） | Research Outcome 专用；显式字段 |
| **Notify price** | `notification/service.py` L212–218 | `notify_price` | Notification Outcome 专用 ✅ |
| **Paper fill price** | `execution_tracking.py` L98, L126 | `fill_price` / `execution.fill_price` | Paper Outcome 专用 |
| **Primary truth** | `outcome_truth.py` | `primary_source`: paper_fill \| signal_close | Research 聚合 ✅ |

**禁止混用（审计确认当前违规点）：**

1. `compute_topk_ablation_alpha()` 读 `horizons` 非 `primary_horizons`
2. `summarize_discovery_sources()` 读 `horizons` 非 `primary_horizons`
3. Notification 与 Research outcomes **未关联**同一 symbol 的三价对比
4. Production cycle `T+N_alpha` 来自 research portfolio_attribution，**不含** notification α

**Phase 4 建议：** 扩展 outcome schema 显式三价；各模块只读对应 entry；测试 `test_v5_4_notification_truth.py` 锁死分离。

---

## 7. Factor Attribution — 模块存在、未接入

### 现有

| 文件 | 功能 | 接入状态 |
|------|------|----------|
| `factors/ic.py` | `factor_ic_report()` — Pearson/Spearman IC, ICIR | ❌ 未调用 |
| `factors/ic.py` | `layer_returns()` — 分位 forward return | ❌ 未调用 |
| `factors/catalog.py` | rs_20, breakout, vol_confirm, trend, board, profit_gap, event, liquidity | ✅ 生产因子 |
| `config/default.yaml` | factors.weights | ✅ |

### V5.4 要求

- Factor Exposure vs Future Return（高/低分 T+5/T+10 α）
- IC / Rank IC / Forward Return
- **RETIRE_CANDIDATE** 建议（**禁止**自动改配置）

**Phase 1/5 建议：** 复用 `factor_ic_report()` + `layer_returns()`，新增 `research/factor_attribution.py` 输出 retire candidates；人工确认 gate。

---

## 8. News / Event / ML Value — 现有度量 vs 所需

### News & Event

| 路径 | 指标 | 问题 |
|------|------|------|
| `tracking.summarize_discovery_sources()` | tag `mean_return` @ single horizon | 非 market/selection α；单 horizon |
| `tracking.summarize_by_source()` | bucket + tag excess | 较好，但未暴露 T+1/10/20 |
| `notification.compute_discovery_attribution()` | notification 子集 α | 与 research 重复、样本更小 |

**V5.4 需回答：** News candidate vs Non-news candidate 的 T+1/5/10/20 α — **需新比较框架**（cohort split，非 tag overlap）。

### ML

| 路径 | 说明 |
|------|------|
| `ml/weight_experiment.py` | Walk-forward ML weight grid — **最接近** ML ablation |
| `candidate/__init__.py` | ML rank 在 union 前 — 可设计 With/Without ML rank 实验 |

**缺口：** 无 `ML Incremental Alpha` 标准指标；无 `ML_COST_INEFFICIENT` 状态标签。

---

## 9. AI Council Value & AI Efficiency

### 现有 Cost 指标

| 位置 | 指标 |
|------|------|
| `ai/cost_tracker.py` | cycle LLM calls, tokens, estimated_usd |
| `model_benchmark.py` | `alpha_per_100k_tokens` |
| `notification/production.py` | cycle cost, cache_hit_rate, notification_llm_cost=0 |

### V5.4 所需

```
AI Efficiency = AI Incremental Alpha / LLM Cost USD
alpha_per_dollar = selection_alpha / llm_cost_usd  (cost=0 → 不除零)
```

多 horizon：T+1, T+5, T+10, T+20。

**状态标签（规格）：**

| 条件 | Status |
|------|--------|
| Δα 显著 + cost 合理 | STRONG |
| Δα 弱 | WEAK |
| Δα 低 / cost 高 | INEFFICIENT |
| 样本不足 | UNPROVEN / INSUFFICIENT_SAMPLE |

**Phase 2/5：** 在 ablation 结果上计算 Efficiency；Alpha Lab 展示。

---

## 10. Production Cycle Metrics（V5.3 复用）

**文件：** `notification/production.py` `record_production_cycle()`

**已记录：** cycle_id, candidate_count, research_count, llm_calls, tokens, cost, BUY/STRONG_BUY, notification_count, T+5/10/20 α（research）

**Stub / 缺口：**

| 字段 | 状态 |
|------|------|
| `paper_fill_count` | 恒为 `None` |
| notification α in cycle | 未写入 |
| alpha validation fields | 未定义（V5.4 Phase 6） |
| AI Efficiency per cycle | 未定义 |

---

## 11. 前端现状 vs Alpha Lab

| 页面 | 内容 | V5.4 差距 |
|------|------|-----------|
| `Research.tsx` Alpha tab | portfolio α, AI Δ, role ablation, model token | 非统一 Lab |
| `Agent.tsx` | researchAlphaDashboard | 分散 |
| `Notifications.tsx` | notification attribution | 仅通知子集 |

**无 `/alpha-lab` 路由。** API 分散：`/api/research/alpha-dashboard`, `/attribution`, `/role-ablation`, `/notifications/stats`。

**Phase 5 建议：** 新页 `AlphaLab.tsx` + `GET /api/alpha-lab` 聚合模块表。

---

## 12. 未来函数与交易边界（审计确认）

| 规则 | 现状 |
|------|------|
| Signal 无 look-ahead | ✅ T close signal, T+1 fill |
| Outcome 只用 as_of 之后价格 | ✅ tracking 按 research_time 切 panel |
| 禁止改 RiskFilter / Paper / QMT | ✅ V5.4 仅 Measurement |
| Attribution 不得用未来新闻/财务 | ⚠️ 需测试锁死；calibration 必须用 primary_horizons |

---

## 13. 二十项审计问答（V5.4 最终目标预检）

| # | 问题 | 当前能否回答 | 证据 / 缺口 |
|---|------|-------------|-------------|
| 1 | 哪种信号最赚钱？ | ⚠️ 部分 | tag mean_return；缺 primary_source + 多 horizon α |
| 2 | 新闻有没有 Alpha？ | ⚠️ 部分 | news tag stats；缺 news vs non-news cohort |
| 3 | 事件有没有 Alpha？ | ⚠️ 部分 | event tag；同上 |
| 4 | ML 有没有 Incremental Alpha？ | ⚠️ 部分 | weight_experiment offline；无标准 Δα |
| 5 | AI Council 有没有 Incremental Alpha？ | ⚠️ 误导风险 | Top-K heuristic ≠ Council off/on |
| 6 | AI 每 $1 产生多少 Alpha？ | ❌ | 无 AI Efficiency |
| 7 | 哪个因子长期无价值？ | ❌ | IC 未运行；无 RETIRE_CANDIDATE |
| 8 | 哪些通知真正值得发？ | ⚠️ 部分 | notification attribution；缺 calibration 闭环 |

---

## 14. P0 / P1 / P2 实施清单（供 Phase 1–6）

### P0 — 度量基础（Phase 1 + 4）

| ID | 项 | 状态 | 建议模块 |
|----|-----|------|----------|
| P0-1 | primary_source / secondary_sources | ❌ | `research/attribution.py` |
| P0-2 | Signal attribution T+1/5/10/20 α | ⚠️ | 扩展 `summarize_discovery_sources` |
| P0-3 | 三价显式字段 + 禁止混读 | ⚠️ | outcome schema + tests |
| P0-4 | 统一 INSUFFICIENT_SAMPLE | ⚠️ | 共享 `minimum_sample` config |

### P1 — Ablation & Efficiency（Phase 2）

| ID | 项 | 状态 |
|----|-----|------|
| P1-1 | No Council vs With Council 实验 | ❌ |
| P1-2 | AI Incremental Alpha @ 4 horizons | ⚠️ 仅单 horizon Top-K |
| P1-3 | AI Efficiency / alpha_per_dollar | ❌ |
| P1-4 | 使用 primary_horizons | ❌ |

### P1 — Calibration（Phase 3）

| ID | 项 | 状态 |
|----|-----|------|
| P1-5 | EER calibration buckets | ❌ |
| P1-6 | Confidence calibration | ❌ |
| P1-7 | bias = mean(pred) - mean(real) | ❌ |

### P2 — Lab & Production（Phase 5–6）

| ID | 项 | 状态 |
|----|-----|------|
| P2-1 | Alpha Lab UI + API | ❌ |
| P2-2 | Factor IC in loop + RETIRE_CANDIDATE | ❌ |
| P2-3 | production_cycles alpha validation fields | ❌ |
| P2-4 | News/Event/ML cohort ablation | ❌ |

---

## 15. 勿重复实现清单（V5.2/V5.3 已有）

以下模块 **禁止** V5.4 重写，仅扩展或调用：

- `research/benchmark.py` — 双 Benchmark
- `research/outcome_truth.py` — paper_fill > signal_close
- `research/tracking.py` — outcomes_for_report, attribution_report（扩展即可）
- `research/canonical_decision.py` — 决策真值
- `portfolio/RiskFilterEngine` — 风控
- `notification/gate.py`, `service.py`, `outcome.py` — 通知链
- `notification/production.py` — cycle metrics（扩展字段）
- `factors/ic.py` — IC 计算（接线即可）
- `ml/weight_experiment.py` — ML walk-forward

---

## 16. 建议 Phase 1–6 执行顺序

| Phase | 交付 | 依赖 |
|-------|------|------|
| **0** | 本审计文档 | — |
| **1** | Signal Attribution + primary_source + 多 horizon α | config `attribution.primary_source_priority` |
| **2** | AI Ablation (A/B) + AI Efficiency | persisted snapshots |
| **3** | Prediction Calibration | Phase 1 outcomes |
| **4** | Notification Truth 字段补全 + 三价测试 | notification/outcome 扩展 |
| **5** | Alpha Lab UI/API + Factor RETIRE_CANDIDATE | Phase 1–3 API |
| **6** | Production validation fields | production.py 扩展 |

每 Phase 完成后：`pytest tests/ -q`（含 `test_v5_4_*.py`）。

---

## 17. 关键文件索引

| 主题 | 路径 |
|------|------|
| Candidate sources | `src/ashare/candidate/__init__.py` |
| Expected return | `src/ashare/research/hypothesis.py`, `snapshot.py` |
| Canonical / rating | `src/ashare/research/canonical_decision.py` |
| Outcomes & α | `src/ashare/research/tracking.py` |
| Outcome truth | `src/ashare/research/outcome_truth.py` |
| Paper fill | `src/ashare/research/execution_tracking.py` |
| Top-K ablation | `tracking.compute_topk_ablation_alpha()` |
| Role ablation | `src/ashare/research/role_ablation.py` |
| Model cost | `src/ashare/research/model_benchmark.py` |
| Factor IC | `src/ashare/factors/ic.py` |
| ML experiment | `src/ashare/ml/weight_experiment.py` |
| Notification outcome | `src/ashare/notification/outcome.py` |
| Production cycles | `src/ashare/notification/production.py` |
| Research 编排 | `src/ashare/services/research.py` |
| 配置 | `config/research.yaml`, `config/default.yaml` |
| 前端 Alpha | `web/src/pages/Research.tsx`, `Notifications.tsx` |
| V5.2 文档 | `docs/V5_2_ALPHA_ATTRIBUTION.md`, `V5_2_OUTCOME_TRUTH.md` |
| V5.3 文档 | `docs/V5_3_COMPLETE.md` |

---

## 18. Phase 0 结论

**Phase 0 审计完成（基于 `e62e2e9`）。**

LongTanRadar 已具备 **Alpha 度量的原材料**（双 benchmark、outcome truth、Top-K AI Δ、notification outcome、production cycles、factor IC 库），但 **尚未成为可回答 V5.4 八个核心问题的 Ablation Framework**。

**下一优先级（Phase 1）：**

1. 配置化 `primary_source_priority` + 写入所有 outcome 记录  
2. 扩展 discovery/signal attribution → T+1/5/10/20 market & selection α  
3. 所有 attribution 统一读 `primary_horizons`  
4. 新增 `tests/test_v5_4_attribution.py`

**本阶段禁止：**

- 新增 AI 角色 / 新闻源 / 模型 / 交易策略  
- 自动删除因子或改生产配置  
- 重写 V5.2 Benchmark / V5.3 Notification

---

*Phase 0 Audit — 只读交付。业务代码未在本步骤修改。实施从 Phase 1 开始。*
