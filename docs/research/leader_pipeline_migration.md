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

## 七、leader_v2：Re-entry / Pullback Buy（本阶段）

### 新增模块

| 模块 | 作用 |
|------|------|
| `pullback_features.py` | 回踩/再加速特征（仅 T 日及以前，带 `feature_as_of`） |
| `reentry_engine.py` | `reentry_score` + components + phase（WAIT→…→BUY_CANDIDATE） |
| `TradeTimingEngine` | EXTREME+无 reentry→WAIT；EXTREME+强 reentry→至多 BUY_CANDIDATE；1 板不得 BUY_* |
| Focus `focus_tier` | CORE / WATCH / BUY_CANDIDATE / BUY_READY |
| `scripts/leader_entry_research.py` | Stage×Entry / Board×Entry + 8 失败股 as-of 复盘 |
| 前端 Entry Timeline | `/leader` 显示 Stage→WAIT→分歧→回踩→再加速→BUY_* |

### 保护未放松

- `buy_ready_min=0.72` / `buy_candidate_min=0.55` / `extreme_stage_cap=0.45` **未降低**
- 非涨停仍不能进 Leader Universe
- 新闻仍是确认层，不是进池器
- `research_only: true` 仍不改 canonical BUY 闸门

### Before → After（2026-08-25 dry-run）

| 指标 | Before (v1) | After (v2) |
|------|-------------|------------|
| BUY_READY | 0 | **0**（正确：当日多 EXTREME 追涨，未满足 TREND+reentry 真买点） |
| BUY_CANDIDATE | 0 | **0**（当日多为 EXTREME+涨停或 1 板；reentry 相位可亮，timing 仍 WAIT） |
| Focus | 8 | **7～8**（跨周期保留；EXTREME→WATCH） |
| canonical BUY | 0 | 0 |
| LLM / Token (dry-run) | 0 / 0 | 0 / 0（rules_only；状态未变不刷 LLM） |

### Entry research 要点（60 只缓存样本，无未来函数输入）

| Entry | n | T+5 mean | Win | T+5 跌停率 |
|-------|---|----------|-----|------------|
| 3 板 | 15 | +4.8% | 64% | 高 |
| 4 板 | 11 | **-6.9%** | 12% | **87.5%** |
| 5 板 | 4 | **-16.9%** | 33% | **100%** |
| EXTREME 追涨 | 15 | 同高板风险 | — | 高 |
| 再加速 | 14 | +1.8% | 54% | **~8%**（跌停率明显更低） |

数据方向：**不要追 4～5 板 EXTREME**；等待分歧/再加速后风险结构更好。样本仍小，继续积累。

### 失败股 as-of 复盘结论

| 股票 | 当时为何“强” | 实际风险 | EXTREME 预警 | 等待分歧 | DROP? |
|------|--------------|----------|--------------|----------|-------|
| 汉森制药 | 5 板 leader 高 | chase=1.0 | ✅ WAIT | 分歧后仍偏弱 | 结构破坏再 DROP |
| 哈森股份 | 高连板 | chase=1.0 | ✅ WAIT | 分歧后 T+5 分化 | 观察 |
| 风范股份 | EXTREME | chase=1.0 | ✅ WAIT | 分歧 T+5 转负 | 警惕 DISTRIBUTION |
| 天洋新材 | EXTREME | chase~0.64 | ✅ WAIT | 分歧接近平 | 未 DROP |
| 白银有色 | EXTREME | chase=1.0 | ✅ WAIT | 分歧弱正 | 观察 |
| 科森科技 | （样本缺 extreme 点） | — | — | 有回踩样本 | — |
| 盈新发展 | EXTREME | chase=1.0 | ✅ WAIT | 分歧 T+5 负 | 警惕 |
| 赤天化 | EXTREME | chase=1.0；追涨 T+5 **-24%** | ✅ WAIT | 分歧 T+5 **+38%** | 验证「等分歧」价值 |

### 验收清单（v2）

| # | 目标 | 状态 |
|---|------|------|
| 1 | 不再追 3～5 板 EXTREME | ✅ WAIT |
| 2 | Focus 长期观察 | ✅ |
| 3 | 正常分歧不立即 DROP | ✅ |
| 4 | 回踩再强 → BUY_CANDIDATE 路径存在 | ✅（规则+测试） |
| 5 | 真条件才 BUY_READY（不降阈值） | ✅ 当日 0 |
| 6 | BREAKDOWN → DROP | ✅ |
| 7 | Token 不因 Focus 爆炸 | ✅ 事件驱动 + hash |
| 8 | 无未来函数 | ✅ 测试覆盖 |

---

## 八、产品逻辑（目标态）

```
涨停池 → 连板/龙头识别 → Stage/Chase → Focus
  → EXTREME → WAIT → 分歧/回踩 → 结构确认 → 再转强
  → Re-entry Score → BUY_CANDIDATE → 新闻确认 → Risk → BUY_READY → 通知
  或 结构破坏 → DROP
```

运行：

```bash
python -m pytest tests/test_reentry_engine.py tests/test_leader_pipeline.py -q
python scripts/leader_pipeline_dry_run.py
python scripts/leader_pipeline_summary.py
python scripts/leader_entry_research.py
```
