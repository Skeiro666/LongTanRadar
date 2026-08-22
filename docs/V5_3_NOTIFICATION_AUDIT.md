# V5.3 Phase 0 Audit — Notification & Production Validation

**Project:** [LongTan Radar](https://github.com/Skeiro666/LongTanRadar)  
**Audit date:** 2026-08-22  
**Code baseline:** `main` post-V5.2 (`2e1029c`)  
**Rule:** Code is authoritative; do not re-implement V5.2 modules.

---

## Executive Summary

V5.2 已建立 **Canonical Decision → RiskFilter → Paper Fill → Outcome Truth** 主链。  
**当前代码中不存在任何 Notification / Webhook / SMTP / Email / WeChat 实现。**  
V5.3 应在 Canonical Decision + RiskFilter 之后、Paper Trading 之前（或并行异步）插入 **Notification Gate**，0 LLM、0 Token。

---

## 二十项审计问答

### 1. Canonical Decision 当前在哪里生成？

| 项 | 详情 |
|----|------|
| **模块** | `src/ashare/research/canonical_decision.py` |
| **函数** | `build_canonical_decision()` (L38), `build_canonical_decisions()` (L106) |
| **编排** | `src/ashare/services/research.py` L286–297 |
| **输出字段** | `research_rating`, `trading_action`, `committee_approve`, `risk_status`, `confidence`, `research_session_id`, `snapshot_id`, `candidate_sources` |

RiskFilter 在 `build_canonical_decision()` 内通过 `risk_allow_fn(bar_like)` 调用 `RiskFilterEngine.allow_open()`。

### 2. RiskFilter 当前在哪里执行？

| 项 | 详情 |
|----|------|
| **引擎** | `src/ashare/portfolio/__init__.py` — `RiskFilterEngine.allow_open()` (L99) |
| **调用链** | `research.py` L279 实例化 → `build_canonical_decisions()` → 每股 `bar_like` 检查 |
| **输出** | `risk_status`: `"pass"` \| `"blocked"` \| `"skipped"`；`risk_flags`: list |

**注意：** Research Gate（`research/gate.py`）是 LLM 前漏斗，与 RiskFilter 不同。Notification Gate 只读 Canonical 中的 `risk_status`。

### 3. Paper Fill 当前在哪里执行？

| 项 | 详情 |
|----|------|
| **入口** | `src/ashare/services/trading.py` — `execute_picks()` (L309) |
| **Broker** | `PaperTradingBroker.place_order()` (L56) |
| **决策源** | `extract_trading_decisions()` — 仅 `committee_approve=True` 的 canonical |
| **触发** | Agent `run_cycle()` L157；API `POST /api/trade/picks` |

**Notification 不得调用此路径。**

### 4. Outcome Truth 当前如何生成？

| 项 | 详情 |
|----|------|
| **模块** | `src/ashare/research/outcome_truth.py` |
| **规则** | `paper_fill > signal_close` → `primary_horizons` |
| **集成** | `tracking.py` `ReviewEngine.attribution_report()` → `apply_primary_truth()` |
| **Horizons** | T+1/3/5/10/20/60（config `research.yaml` tracking.horizons_days） |

Notification Outcome 应使用 **通知时刻价格** 作为 entry（独立于 research signal close）。

### 5. Research Session 如何唯一标识？

| 项 | 详情 |
|----|------|
| **格式** | `R{YYYYMMDD}{6-hex-upper}` — `snapshot.py` L68 |
| **Gate skip** | `G{YYYYMMDD}{6-hex-upper}` — `session.py` L165 |
| **Canonical 字段** | `research_session_id` = `research_id` = `snapshot_id` |
| **持久化** | `data/research_snapshots/{id}.json`, `data/research_sessions.jsonl`, PG `research_sessions` |

### 6. Snapshot 如何唯一标识？

与 `research_id` 相同。完整 snapshot 存于 `data/research_snapshots/{research_id}.json`，含 council/chairman/evidence/candidate_score_meta。

### 7. 当前是否已经存在 Notification？

**否。** 全仓库搜索 `notification`, `webhook`, `smtp`, `email`, `wechat` 零匹配。

### 8. 当前是否已经存在 Webhook？

**否。**

### 9. 当前是否已经存在 SMTP？

**否。**

### 10. 当前前端 Research URL 是什么？

| 路由 | 页面 |
|------|------|
| `/research` | 圆桌研报（Research.tsx） |
| `/agent` | 研究循环 |
| `/` | 总览 |

**无** `/research/:id` 动态路由。  
API: `GET /api/research/session/{research_id}` 已存在（`api.ts` L88）但未在前端调用。  
V5.3 通知 deep link 建议: `{PUBLIC_BASE_URL}/research?session={research_id}` 或 API URL。

### 11. 最适合插入 Notification Gate 的位置？

**Primary（推荐）：** `research.py` 在 `persist_report()` 之后、`return payload` 之前 — 异步调度 Notification Job，不阻塞 Research。

```
build_canonical_decisions + RiskFilter  (L286-297)
    ↓
attribution / outcome                   (L305-334)
    ↓
persist_report                          (L516)
    ↓
【V5.3】schedule_notification_job()      ← 异步，0 LLM
    ↓
return payload
```

**理由：**
- Canonical + Risk 已 finalized
- Snapshot 已 persisted
- 发送失败不影响 Research 成功
- 不侵入 `trading.py` / `agent.py`

**RISK_EXIT 补充：** 需读取 paper positions（`PaperTradingBroker.get_positions()`），在 gate 阶段合并 held symbols + `risk_status=blocked`。

### 12. 如何做到 Notification 0 LLM calls？

| 要求 | 实现 |
|------|------|
| 不调用 AI client | Gate/Formatter 纯 Python 字符串模板 |
| 不重新研究 | 只读 persisted snapshot + canonical |
| 不拉新闻 | 使用 snapshot 内已有 news_package / evidence |
| 不调用 roundtable | 忽略 benchmark_only roundtable |

`formatter.py` 从 snapshot 渲染：Chairman、Role Reports、Evidence IDs、RiskFilter 结果。

### 13. 如何实现 Notification Outcome？

新建 `notification/outcome.py`：

1. 通知发送时记录 `notify_price`（panel close at notify_time）
2. T+1/5/10/20 用 TrackingEngine 同类逻辑计算 return / market_alpha / selection_alpha
3. 汇总 `notification_attribution` — 按 BUY / STRONG_BUY / RISK_EXIT 分组
4. `sample_count < minimum_sample` → `INSUFFICIENT_SAMPLE`

Discovery Attribution 复用 `tracking.py` `summarize_by_source()` 模式，按 candidate_sources 统计。

---

## 当前架构（Notification 插入点）

```
Market → Candidate → Factor/Profit/Event/News/ML
    ↓
Research Gate → Dynamic Council → Chairman
    ↓
build_canonical_decisions + RiskFilterEngine     ← 通知输入
    ↓
【V5.3 Notification Gate】NOTIFY / SKIP            ← 0 LLM
    ↓
【V5.3 Async】WeChat / Email
    ↓
Human（人工决策）
    ↓
execute_picks → Paper Fill → Outcome Truth
    ↓
【V5.3 Notification Outcome / Attribution】
```

---

## 关键文件索引

| 主题 | 路径 |
|------|------|
| Canonical Decision | `research/canonical_decision.py` |
| RiskFilter | `portfolio/__init__.py` |
| Paper Fill | `services/trading.py` |
| Outcome Truth | `research/outcome_truth.py` |
| Snapshot | `research/snapshot.py`, `research/session.py` |
| Research 编排 | `services/research.py` |
| Benchmark | `research/benchmark.py` |
| Tracking | `research/tracking.py` |
| LLM Budget | `research/llm_budget.py` |
| 前端 | `web/src/pages/Research.tsx`, `web/src/App.tsx` |
| API | `api/app.py` |

---

## V5.3 实施计划

| Phase | 内容 |
|-------|------|
| 0 | 本审计文档 |
| 1 | `notification/` domain — gate, dedup, cooldown, priority, models, tests |
| 2 | WeChat webhook + SMTP email, async, retry, tests |
| 3 | Notifications 前端页 + Research 通知状态 + API |
| 4 | Notification outcome, attribution, production validation, tests |

---

## 禁止事项（V5.3）

- 不重新实现 V5.2 Benchmark / Alpha / Cache / Gate / Lifecycle / Budget
- 不自动交易（不调用 broker / QMT）
- 不调用 LLM 生成通知文本
- 不硬编码 Webhook / SMTP 凭证
- 不伪造 unavailable 的 confidence / expected_excess_return

---

*Phase 0 Audit — 2026-08-22。下一步：Phase 1 Notification Domain。*
