# CURRENT_ARCHITECTURE — A 股 AI 量化投研平台（现状）

> **产品介绍以 [README.md](README.md) 为准。** 本文保留模块级对照。  
> 2026-08-22 起：因子 / 利润断层 / 事件 / 候选漏斗 / ML 排序 / Council / 快照 / 新闻情报已落地。  
> LLM 评级 ≠ 交易动作；新闻不绑定东方财富；东财 PC 终端不是数据源。

---

## 0. 命名澄清（重要）

仓库中**不存在**注册策略名 `ml_lgbm_value`。

| 口头称呼 | 实际含义 |
|----------|----------|
| `ml_lgbm_value` | 遗留路径：`strategy.name ∈ {ml_lgbm,lgbm,ml}` + `picks_style ∈ {value,mean_reversion,mr}` + **`research.enabled=false`**；reason 标签写成 `ml_lgbm_value` |
| `ml_lgbm`（回测） | [`MLLgbmStrategy`](src/ashare/strategy/ml_lgbm.py)：月频 Top-N，**仅** LightGBM 原始预测等权，**不含** anti_chase Value 合成 |
| 产品默认 | `research.enabled=true`，`strategy.name=leader`：事件/利润断层池 → 因子 → AI 圆桌 |

「Value」在遗留路径中 = **均线偏离均值回归**（`ma_gap_20/60`），代码注释已写明**不是基本面估值**。见 [`anti_chase.py`](src/ashare/strategy/anti_chase.py) `FEATURE_NOTE` / `mean_reversion_score`。

---

## 1. 当前系统架构

### 1.1 目录结构（核心）

```
lianghua_daA/
├── config/default.yaml          # 主配置
├── config/agent_overrides.yaml  # Agent/优化器运行时覆盖
├── .env                         # AI_* / DB / Redis（勿提交密钥）
├── data/
│   ├── cache/daily/*.parquet    # 行情缓存
│   ├── models/<run_id>/         # LightGBM 模型 + meta.json
│   ├── reports/latest.json|.md  # 研报
│   └── paper_state.json         # 模拟盘
├── src/ashare/
│   ├── main.py                  # CLI
│   ├── api/app.py               # FastAPI
│   ├── data/                    # 行情 / 缓存 / 筛选
│   ├── pool/                    # 龙头/事件池
│   ├── factors/                 # 研究因子库（8 个）
│   ├── ml/                      # LightGBM 特征/数据集/训练/注册
│   ├── strategy/                # on_date 策略（含 ml_lgbm / leader）
│   ├── ai/                      # LLM 客户端 / 圆桌 / 复盘
│   ├── services/                # research / picks / agent / trading
│   ├── backtest/engine.py       # T+1 回测
│   ├── risk/guard.py
│   ├── brokers/                 # paper / qmt 壳
│   └── db/                      # PG schema + Redis
└── web/src/pages/               # Overview / Research / Agent
```

### 1.2 产品默认数据流

```
AkShare(涨停/强势/业绩预告/现货)
        ↓
  build_leader_pool          [pool/builder.py]
        ↓
  ensure_panel(OHLCV)        [data/provider.py]
        ↓
  score_candidates(8 因子)   [factors/score.py]
        ↓
  Top-N shortlist
        ↓
  run_roundtable             [ai/roundtable.py]
        ↓
  data/reports + Redis + picks 表
        ↓
  (可选) execute_picks       [services/trading.py]
```

定时：`agent.autostart` → [`services/agent.py`](src/ashare/services/agent.py) 周期调用 `run_picks` → 默认即 `run_research`。

### 1.3 模块依赖（简图）

```
main / api / agent
    ├── services.research ──► pool + factors + ai.roundtable + data
    ├── services.picks    ──► research（默认）或 _legacy_ml_picks
    ├── ml.train          ──► data.provider + ml.dataset + ml.features
    ├── backtest.engine   ──► strategy.on_date + risk + PaperBroker
    └── ai.client         ──► OpenAI-compatible 聚合商
```

---

## 2. 数据来源与股票数据模型

| 项 | 实现 |
|----|------|
| Provider | `akshare` / `sample`（[`config/default.yaml`](config/default.yaml) `data.provider`） |
| 日线 | AkShare EM/Sina 等，**前复权**，缓存 parquet |
| Bar | `date, symbol, open, high, low, close, volume, amount, pct_chg, is_st, is_halt, limit_up, limit_down` |
| 现货筛选 | [`data/screen.py`](src/ashare/data/screen.py) |
| 事件 | [`pool/events.py`](src/ashare/pool/events.py)：涨停池、强势池、业绩预告利润断层 |
| 名称 | [`data/names.py`](src/ashare/data/names.py) + `stock_names.json` |

**当前缺失（不可伪造）：**

- 行业/板块成分与行业指数收益（无法做真·sector relative strength）
- 按**公告披露日**对齐的 PE/PB/ROE/财报序列
- 指数日线基准序列（沪深300/中证500 等）用于超额收益与回测 Alpha
- 可历史复现的涨停/公告/新闻时间序列

---

## 3. 数据库 / 缓存 / 配置

### 3.1 PostgreSQL（[`src/ashare/db/schema.sql`](src/ashare/db/schema.sql)）

仅交易相关：`picks`, `orders`, `fills`, `positions_snapshot`, `account_snapshot`。  
**无** `research_sessions` / snapshot / outcome 等投研表。

### 3.2 Redis

- `ashare:picks:latest`
- `ashare:research:latest`

### 3.3 文件产物

- 研报：`data/reports/latest.json`, `latest.md`, `{as_of}.json`
- 模型：`data/models/<run_id>/model.joblib`, `meta.json`, `latest.json`
- 模拟盘：`data/paper_state.json`

### 3.4 配置

- [`config/default.yaml`](config/default.yaml)：universe / pool / factors / research / ml / ai.committee / risk / backtest
- `config/agent_overrides.yaml`：运行时覆盖
- `.env`：`AI_API_KEY`, `AI_BASE_URL`, `AI_PROVIDER`, 各角色 `AI_*_MODEL` 等

---

## 4. 策略入口

[`strategy/__init__.py`](src/ashare/strategy/__init__.py) `build_strategy(cfg)`：

| `strategy.name` | 类 |
|-----------------|-----|
| `leader` / `dragon` / `leader_factor` / `roundtable` | `LeaderFactorStrategy` |
| `ml_lgbm` / `lgbm` / `ml` | `MLLgbmStrategy` |
| `multi_factor` / `factor` | `MultiFactorStrategy` |
| `dual_ma` / `ma` | `DualMAStrategy` |
| `ai_select` / `ai` / `llm` | `AISelectStrategy` |

**Live 选股路由**（[`services/picks.py`](src/ashare/services/picks.py)）：

- `research.enabled` 且策略不是 dual_ma → **`run_research`**（忽略 ML 路径）
- 否则 → `_legacy_ml_picks`

---

## 5. ml_lgbm_value 完整调用链

### 5.1 启用条件

```
research.enabled = false
strategy.name ∈ {ml_lgbm, lgbm, ml}
strategy.picks_style ∈ {value, mean_reversion, mr}
```

### 5.2 链路

```
run_picks
  → _legacy_ml_picks
  → resolve_universe + ensure_panel
  → feature_row_from_closes          [ml/features.py]
  → load_model.predict → ml_score    [ml/registry.py]
  → enrich_structure
  → passes_anti_chase / passes_ml_floor
  → score_cross_section              [strategy/anti_chase.py]
       mr_raw = -0.6*ma_gap_20 - 0.4*ma_gap_60
       score = w_mr*z(mr) + w_ml*z(ml) - conflict_penalty - chase
  → allocate_weights
  → payload.reason = ml_lgbm_{style}  # 即 ml_lgbm_value
```

### 5.3 训练链路（独立）

```
CLI train | POST /api/train
  → train_model                      [ml/train.py]
  → ensure_panel → build_dataset     [ml/dataset.py]
  → enrich_symbol (features + label) [ml/features.py]
  → time_split（按交易日时间切分，非 random）
  → LGBMRegressor 小网格，valid Spearman IC − MSE 选参
  → save_run → data/models/<run_id>/
```

**Label：** `close[t+h]/close[t] - 1`，默认 `h=5`（**绝对收益**，非相对基准超额）。

### 5.4 回测链路（≠ value 合成）

```
build_strategy → MLLgbmStrategy.on_date（月尾）
  → predict → Top-N 等权（cap max_name/gross）
  → RiskGuard → T+1 PaperBroker 成交
```

---

## 6. 当前因子

### 6.1 研究路径（8）

| 名 | 含义 |
|----|------|
| `rs_20` | 近 20 日涨幅（**不是**相对行业） |
| `breakout` | 相对 20 日高点 |
| `vol_confirm` | 量比 |
| `trend` | MA20/MA60 站位 |
| `board` | 连板/强势标记（池 meta） |
| `profit_gap` | 业绩预告强度（池 meta） |
| `event` | 事件分（池 meta） |
| `liquidity` | log(成交额) |

截面 z-score + [`factors.weights`](config/default.yaml) 加权 → `score`。

### 6.2 ML 特征（8）

`mom_5, mom_20, vol_20, vol_ratio, ma_gap_20, ma_gap_60, ret_1, high_low`

### 6.3 遗留「Value」

`mean_reversion_score` = 对 `ma_gap` 的负向加权 — **技术回调，非 PE/PB**。

---

## 7. 当前股票池逻辑

[`pool/builder.py`](src/ashare/pool/builder.py) `build_leader_pool`：

1. 可选：涨停池、强势池、业绩预告（利润断层代理）
2. 可选：现货技术龙头（涨幅 + 成交额）
3. 合并去重，过滤 ST / BJ / 科创 / 流动性 / 价格
4. 截断 `pool.max_candidates`（默认 40）

历史回测中的 `LeaderFactorStrategy` **无法**稳定复现实时涨停/预告接口，用价格技术因子**代理** board/profit_gap/event。

---

## 8. 当前评分与仓位

| 路径 | 评分 | 仓位 |
|------|------|------|
| 研究 | 因子加权 z + 主席 verdict | `buy` 等权；非 buy → 0 |
| 遗留 ML+value | ML_z + MR_z − 冲突/追涨惩罚 | `weight_scale` 归一 + `max_name_weight` |
| 回测 ml_lgbm | 原始 predict | Top-N 等权 |
| 风控 | — | `RiskGuard`：单票/总仓/回撤/日亏；停牌只许卖 |

---

## 9. 当前 LightGBM

| 项 | 现状 |
|----|------|
| 角色 | 旁路训练/回测；**默认 live 研究不调用** |
| 目标 | 未来 h 日绝对收益 |
| 切分 | 按日时间切分 `valid_ratio`；**无** Walk-Forward；**无** 独立 Test |
| 选参 | 仅在 validation 上比较；无 purge/embargo |
| 预测 | `model.predict(FEATURE_COLS)` |
| 解释 | `feature_importance` 写入 meta；live 研报不展示 SHAP |

---

## 10. 当前 AI 模块

| 组件 | 路径 | 说明 |
|------|------|------|
| Client | [`ai/client.py`](src/ashare/ai/client.py) | 聚合商 OpenAI 兼容；角色继承 base_url/key，覆盖 model |
| 圆桌 | [`ai/roundtable.py`](src/ashare/ai/roundtable.py) | 角色：dragon / event / risk / chair；verdict：buy/watch/pass |
| 复盘 | `ai/review.py`, `trade_review.py` | 回测/交易文本复盘；**非**研究结论 1D–60D 自动跟踪 |
| 优化器 | `ai/optimizer.py` | 可写 agent_overrides |

**与目标差距：** 无独立 Fundamental / Valuation / Bear；无强制 Debate 轮；Research Rating 与 Trading Action 未分离；`committee_approve` 可直接驱动交易。

---

## 11. 当前回测

[`backtest/engine.py`](src/ashare/backtest/engine.py)：

- T 收盘信号 → T+1 open/close 成交；手数 100；佣金/印花税/滑点
- 指标：总收益、年化、MaxDD、Sharpe、换手、胜率、按年收益
- **缺失：** Sortino、Calmar、Alpha、Beta、IR、基准对比、IS/Validation/OOS 分区报告

---

## 12. API / 前端 / 日志

**API（节选）：** `/api/health`, `/config`, `/train`, `/backtest`, `/picks/*`, `/research/*`, `/agent/*`, `/trade/*`, `/factors`, `/account`, `/pnl`

**前端：** Overview（权益）、Research（圆桌研报）、Agent（循环状态）

**日志：** `monitor.log_dir`；Agent 带 `phase` 结构化字段

---

## 13. 当前存在的问题

1. 「Value」概念误导（均线 ≠ 估值）
2. Live 研究与 LGBM 脱节；BT `ml_lgbm` ≠ 遗留 value 合成
3. Label 非超额收益；无 Walk-Forward / 独立 OOS
4. 无行业、无 as-of 财务 → 无法实现目标中的真 Value/Quality/sector RS/利润断层序列
5. 事件池不可历史复现；Leader 回测代理乐观
6. 研报缺少完整输入 Snapshot / Prompt·Model 版本
7. 无 Research Outcome 自动复盘；无法证明 AI 是否贡献 Alpha
8. AI 结论可直接变成交易动作
9. 回测指标与基准不足
10. Token 漏斗依赖人工 top_n，未工程化「5000→500→50→10」

---

## 14. 可复用的代码

| 模块 | 用途 |
|------|------|
| `data/provider`, `store`, `akshare_source` | 行情与缓存 |
| `pool/builder`, `pool/events` | 候选池骨架 |
| `factors/score` 截面 z 思路 | 标准化模板 |
| `ml/train`, `dataset`, `registry` | 训练壳（需换特征/目标/切分） |
| `ai/client` | LLM 调用 |
| `ai/roundtable` | 多角色编排雏形 |
| `backtest/engine` T+1 循环 | 回测底座 |
| `risk/guard`, `PaperBroker` | 风控与模拟成交 |
| `services/research` 编排 | 研究管线入口 |
| `api/app`, `web` 三页 | 展示壳 |

---

## 15. 需要重构 / 新建的代码

| 目标模块 | 动作 |
|----------|------|
| FactorEngine | 新建：元数据 + 30~40 因子；与旧 `FEATURE_COLS` / 8 因子统一 |
| ProfitInflectionEngine | 新建：真假分级；现仅有预告标量 |
| EventEngine | 结构化事件对象；替代散落 meta |
| CandidateEngine | 漏斗与规模控制 |
| ML Ranking Layer | 超额收益、Walk-Forward、LeakageDetector |
| ResearchSession + Snapshot | 输入数据版本化持久化 |
| AICouncil / Debate / Chairman | 6 角色 + 冲突辩论 + Rating≠Action |
| Tracking / Review | 1D–60D outcome；Quant vs Quant+AI |
| DB | **新增** research_* 表，**不破坏**现有 picks/orders |
| 配置 | `factors.yaml` / `research.yaml` / `prompts.yaml` / `models.yaml` |
| 回测指标 + 基准 | 扩展 `BacktestResult` |

**保留：** `ml_lgbm` 与 `_legacy_ml_picks` 可继续运行；不删除旧策略。

---

## 16. 未来数据泄漏风险（现状报告，未在本 Phase 修复）

| 风险 | 位置 | 严重度 |
|------|------|--------|
| 当前 ST 名单回填到历史全部 bar | `akshare_source` 归一化 | 高 |
| Label 日重叠 + 无 purge/embargo | `ml/dataset.time_split` | 中 |
| 超参只在 validation 上选，无最终 OOS | `ml/train.py` | 中 |
| 前复权历史修订 | AkShare qfq | 低~中 |
| Leader BT 用当日价格代理事件因子 | `strategy/leader.py` | 中（非未来 bar，但是伪事件） |
| 训练宇宙用「拉取时刻」龙头名单而非历史成员 | `ensure_panel` + pool | 中 |
| Random split | — | **不存在** |

特征计算本身使用过去窗口 / `shift`，**特征侧无明显未来 bar 泄漏**。

---

## 17. 推荐改造顺序

严格分 Phase，**每 Phase 自测通过后再进入下一 Phase**：

1. **Phase 1** — 本文档（完成）
2. **Phase 2** — FactorEngine（技术因子实装；Value/Quality/行业 RS：**接口 + available=false**）
3. **Phase 3** — ProfitInflectionEngine
4. **Phase 4** — EventEngine 结构化
5. **Phase 5** — CandidateEngine 漏斗
6. **Phase 6** — ML Ranking + Walk-Forward + LeakageDetector
7. **Phase 7–10** — ResearchSession / Council / Debate / Chairman
8. **Phase 11–13** — Snapshot / Tracking / Review + A/B
9. **Phase 14** — Backtest 指标与基准
10. **Phase 15** — API / 前端结构化投研卡片

数据原则：**缺 as-of 财务/行业时不伪造**；先把技术 + 现有事件池 + ML 排序 + 圆桌可复盘做扎实。

---

## 18. Phase 1 验收清单

- [x] 目录与模块依赖已梳理
- [x] 数据模型与缺口已标明
- [x] `ml_lgbm_value` 真实调用链已写清（含命名澄清）
- [x] 因子 / 池 / 评分 / LGBM / AI / DB / 回测已记录
- [x] 可复用 vs 需重构已列出
- [x] 泄漏风险已报告（未偷偷修改）
- [x] 改造顺序已给出
- [x] 业务代码：本 Phase **零修改**（仅新增本文件）
