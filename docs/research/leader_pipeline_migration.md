# LongTanRadar 龙头架构迁移报告

**定位：** 涨停龙头股研究与交易时机识别系统（非全市场价值/ML/新闻选股）

**模式：** `leader.research_only: true` — 只标注 lifecycle / timing，不自动放宽 canonical BUY 阈值

---

## 一、Pipeline 前后对比

| 层级 | 旧 Pipeline (Audit 2026-08-24) | 新 Pipeline (leader_v1) |
|------|-------------------------------|-------------------------|
| 入口 | 2337 → 780 筛选 → 60 池（含 tech_leader 补齐） | 涨停池 hard gate；`block_non_limit_up_in_pool` 禁用 tech_leader 污染 |
| 龙头识别 | 与 candidate_score / ML 混合排名 | `LeaderRankingEngine`：连板 + consecutive 优先 |
| 买点 | Council rating → canonical BUY | **分离** `leader_score` vs `trade_timing_score` |
| Stage | 无正式引擎 | `StageEngine`: EARLY/TREND/ACCELERATION/EXTREME/DISTRIBUTION/BREAKDOWN |
| 追涨风险 | anti_chase 仅研究 | `ChaseRiskEngine`: chase_score + LOW/MEDIUM/HIGH/EXTREME |
| 时机 | 无 | `TradeTimingEngine`: BUY_READY / BUY_CANDIDATE / WAIT / PASS |
| Focus | 无持久化 | `FocusWatchlistStore` 跨轮次保留 FOCUS/BUY_* |
| Council | 20 只全量 LLM | 仅 FOCUS/BUY_CANDIDATE/BUY_READY → `council_tier=full` |
| 新闻 | Top-20 全量抓取 | 分层：`rules_only` → `local_llm_light` → `local_llm_full` |
| 前端 | 无 | `/leader` 龙头监控页 + Stage/Board Dashboard |

---

## 二、核心设计原则（已落地）

1. **非涨停不进龙头研究池** — `LimitUpUniverse.filter_rows`
2. **龙头 ≠ 买点** — EXTREME 默认 `WAIT`，不是 PASS 也不是 BUY
3. **Focus 不因一次排序失败消失** — `merge_cycle` + `merged_from_focus`
4. **踢出规则** — BREAKDOWN / 严重负面 / stale 无改善
5. **Token 分层** — scan 零 Council LLM；Focus 才 full council
6. **无未来函数** — Stage/Chase/Features 仅用 T 日及以前 bars

---

## 三、验收测试 (`tests/test_leader_pipeline.py`)

| # | 验收项 | 状态 |
|---|--------|------|
| 1 | 非涨停不能进 Leader Universe | ✅ |
| 2 | 连续涨停优先级高于单板 | ✅ |
| 3 | Focus 股票 off-rank 仍保留 | ✅ |
| 4 | Focus BREAKDOWN / 严重负面 → DROP | ✅ |
| 5 | BUY_READY 需 timing + risk | ✅ |
| 6 | EXTREME → WAIT | ✅ |
| 7 | scan tier 跳过 full council | ✅ |
| 8 | 状态未变跳过 news LLM | ✅ |
| 9 | 相同 payload hash 跳过 | ✅ |
| 10 | Stage features 无未来数据 | ✅ |

---

## 四、已知剩余风险

1. **Canonical BUY 仍为 0** — Council 输出 `WAIT_FOR_CONFIRMATION`；`research_only=true` 故意不改阈值
2. **T 日涨停 risk filter** — 同日 limit_up 仍阻止开仓（T+1 设计正确，但通知时机需人工理解）
3. **Stage/Board Performance Dashboard** — 当前为当轮样本统计；完整 T+N 反事实需 `counterfactual` 脚本回填
4. **8 只失败股复盘** — 需 as-of 重跑 stage/chase/timing（`scripts/buy_pipeline_audit.py` 可扩展）
5. **BUY_READY 通知** — 代码已预留 `leader.notification.buy_ready_alert`；`research_only=false` 后才接 Email/微信

---

## 五、运行方式

```bash
# 研究循环
python -m ashare.main research

# Pipeline 摘要
python scripts/leader_pipeline_summary.py

# 测试
python -m pytest tests/test_leader_pipeline.py -q

# API
GET /api/leader/monitor
GET /api/leader/dashboard
```

---

## 六、2026-08-25 Dry-Run 实测（`scripts/leader_pipeline_dry_run.py`）

| 指标 | 旧 Audit | 新 Pipeline (dry-run) |
|------|----------|----------------------|
| 池入口 | 60（利润断层+tech_leader 混合） | 60 池 → **43 涨停通过** / 17 NOT_LIMIT_UP 剔除 |
| 研究池 | 20 全量 Council | 20（scan 17 + FOCUS full 1） |
| Council LLM | 20 只 × 多角色 | dry-run **0 Token**（仅规则+本地特征） |
| canonical BUY | 0 | 0（research_only，未改阈值） |
| trade_timing BUY_READY | 无 | **0**（正确：当日 EXTREME 高追一律 WAIT） |
| Focus Watchlist | 无 | **8 只**（汉森制药 FOCUS 持续跟踪） |

**Focus 重点股（2026-08-25）：**

| 代码 | 名称 | 连板 | Stage | Chase | Timing | 结论 |
|------|------|------|-------|-------|--------|------|
| 002412.SZ | 汉森制药 | 5 | EXTREME | 1.00 | WAIT (0.16) | FOCUS，不追涨 |
| 000017.SZ | 深中华A | 4 | EXTREME | 1.00 | WAIT | LEADER_CONFIRMED |
| 003040.SZ | 楚天龙 | 3 | EXTREME | 0.97 | WAIT | LEADER_CONFIRMED |

**汉森制药验证（Audit 失败股）：** 若旧系统按 leader_score 直接 BUY，5 板 EXTREME chase=1.0 会被误买；新系统 **leader_score=0.9 但 trade_timing=WAIT**，符合「强龙头 ≠ 买点」设计。

---

## 七、产品逻辑（目标态）

```
涨停池 → 连板/龙头识别 → Stage/Chase → Focus Watchlist
  → 持续监控 → 买点出现 → BUY_READY → 通知
  或 结构恶化 → DROP
```
