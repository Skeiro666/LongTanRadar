# 龙探雷达（LongTan Radar）— 项目全貌（给外部模型审阅用）

本文是 **2026-08-22 代码现状** 的自包含说明。不依赖仓库其它文档。  
用途：复制给 ChatGPT / Claude 做架构评审。评审时请按「已实现」理解，不要按理想量化平台脑补未写明的能力。

---

## 1. 这是什么 / 不是什么

**是：** 中国 A 股 **日频** 投研与模拟交易系统。核心产品句：

> 机器找候选 → 新闻/事件规则打分 → AI 多角色做研究评级 → 人看研报决策。  
> 研究评级 ≠ 买卖指令。LLM 不是唯一交易开关。

**不是：**

- 加密货币 / 高频 / Level-2 撮合
- 用东方财富 PC 客户端（`D:\eastmoney\dfcf`）当数据 SDK（那是给人眼看盘的 GUI，本地 `.dat` 不读）
- 「把新闻原文扔给大模型，让它改选股公式」
- 默认全市场回调捡便宜（遗留 `ml_lgbm` + 均线偏离均值回归，需显式关研究管线才走）

默认 `BROKER_MODE=paper`，agent **不会**自动打开 QMT 实盘。

---

## 2. 硬约束（回测与模拟都必须遵守）

| 规则 | 说明 |
|------|------|
| 无未来函数 | T 日收盘信息出信号，T+1 开盘或收盘成交；禁止用当日收盘价成交当日信号 |
| 交易制度 | 手数 100、卖出印花税、佣金/过户、滑点 |
| 市场约束 | 停牌、涨跌停、ST 过滤 |
| 数据诚实 | 没有 as-of 财务 / 行业成分 / 一致预期时，对应因子标记 `available=false`，禁止伪造 PE/PB/ROE |
| 新闻诚实 | 搜索命中 ≠ 该股新闻；实体关联带置信度；`as_of` 之后的新闻丢弃 |

---

## 3. 怎么跑起来

- 后端：`python -m ashare.main serve` → FastAPI `http://127.0.0.1:8000`
- 前端：Vite `http://127.0.0.1:5173`（总览 / 圆桌研报 / 研究循环）
- 配置：`config/default.yaml` + `.env`（`AI_API_KEY`、`AI_BASE_URL`、各角色 `AI_MODEL_*`）
- LLM：任意 OpenAI 兼容网关（硅基流动 / 阿里云百炼）。一个 Key + 一个 URL，圆桌只换 model 名。Key 未配则启发式兜底。
- PG / Redis 可选；连不上仍可跑，持久化告警。
- 行情：`data.provider=akshare`，日线前复权缓存 `data/cache/daily/*.parquet`；失败可用 `sample` 合成数据。
- `agent.autostart: true`，默认每 1800 秒一轮。改 `.env` 必须重启 API。

页面：总览看权益/持仓；圆桌研报看池、因子、新闻包、角色论点、buy/watch/pass；研究循环可启停/重置。

---

## 4. 主运行逻辑（产品默认路径）

入口：`serve` → `agent.autostart` → `services/agent.py` `run_cycle`  
或网页/CLI：`research` / `POST /api/research/run` / `POST /api/agent/cycle`

每一轮 **agent cycle**：

```
1. picks = run_picks()          # 默认即 run_research()
2. execute_picks()              # 仅 committee_approve / buy 才模拟买入
3. 记权益
4. optimizer 根据模拟盘+圆桌摘要，改因子权重/池门槛（不读新闻正文）
5. 若提案 retrain=true，重训遗留 LightGBM（非主路径）
6. sleep interval_sec
```

### 4.1 `run_research` 内部（两条并行，结果会合并）

**路径 A — 遗留投委会（仍参与模拟买入习惯字段）**

```
AkShare 涨停池 / 强势池 / 业绩预告
    → pool/builder.py 龙头事件池（价格成交额 ST 创业板等过滤）
    → ensure_panel 日线
    → factors/score.py 8 因子截面打分（rs_20, breakout, vol_confirm, trend, board, profit_gap, event, liquidity）
    → Top-N shortlist（strategy.top_n，默认 3）
    → ai/roundtable.py 四角色：龙头 / 事件 / 风控 / 主席
       输入含 K 线摘要 + news_package（或降级标题）
    → 输出 committee_verdict: buy | watch | pass
```

**路径 B — 平台引擎（研究主叙事）**

```
同一股票池
    → CandidateEngine 漏斗（绝不把全市场塞进 LLM）
         利润断层 ProfitInflectionEngine
         事件 EventEngine（池标签规则：预增/减持/涨停等 prior）
         FactorEngine as-of 因子
         先按 leader/利润/事件粗排，截断 max_research_pool（默认 20）
         再对这 20 只拉新闻，用 news_score 重排
    → MLRankingEngine 超额收益预测 hint（失败则跳过）
    → 最多 max_council / top_n 只进入 ResearchSessionEngine
         Snapshot（量化+事件+新闻包+版本号）
         六角色并行 Council：fundamental / quant / event / valuation / bear
         Debate
         Chairman：research_rating 与 trading_action 分开
    → 风控 RiskFilterEngine
    → 仅当：风控允许 AND trading_action==SMALL_POSITION AND rating∈{BUY,STRONG_BUY}
       才 committee_approve=true（模拟可买）
    → 否则 WATCH/PASS，研报仍保存
```

路径 B 成功则 **picks 用平台映射结果**，路径 A 的圆桌仍挂在 payload 里给人看。路径 B 失败则退回路径 A。

### 4.2 新闻在链路里的真实位置（容易误解）

新闻 **不是** 优化器的输入。优化器只允许改：`top_n`、池门槛、8 个因子权重、是否重训 LGBM。Prompt 禁止改回「回调捡便宜」。

新闻用于：

1. **机器打分：** `net_event_score` → `candidate_score` 里约 15%（`config/news.yaml` `candidate_weights.news`）。规则抽取订单/减持/业绩等，不是 LLM 自己打分。
2. **AI 研究证据：** 按角色过滤后进入 Council / 圆桌。用来论证，不单独当买点。
3. **展示与复盘：** 研报页 24h/7d/30d、冲突、预期差；snapshot 记 `news_ids`。

流水线：多源抓取 → jsonl 落盘 → 去重 → 实体关联（弱匹配低置信）→ 分类 → 事件抽取 → 质量/时效/相关打分 → 打包。  
缺一致预期时 `expectation.available=false`。

新闻源（`config/news.yaml` `providers` 顺序，单源失败降级）：

| 源 | 作用 |
|----|------|
| baidu 百度股市通 | 个股新闻 + 第三方原文 URL（同花顺/东财/证券时报等聚合） |
| eastmoney 搜索 | 个股 CMS 标题摘要 |
| sina 滚动 | 公司名/代码关键词 |
| ths 同花顺 7x24 | **只作全市场快讯，不当个股新闻**（过滤不稳定，防错绑） |

未接：交易所公告原文、雪球（WAF）、部分财联社/腾讯接口。  
质量档：公告/交易所 A，证券时报等 B，聚合站 C。

### 4.3 成交

`services/trading.py` + `brokers/paper.py`。默认纸面账户初始资金约 3000 元（配置 `paper.initial_balance`）。现金不够 1 手则跳过买入、研报保留。`ai.trade_review` 默认 false。

---

## 5. 架构（模块）

```
CLI main.py / FastAPI api/app.py / Agent
    ├─ services.research     研究主流程
    ├─ services.picks        默认转 research；research.enabled=false 才走遗留 ML 选股
    ├─ services.trading      模拟成交
    ├─ services.agent        循环 + 优化器
    ├─ pool.builder          涨停/强势/预告/技术龙头
    ├─ data.provider         AkShare 缓存 / sample
    ├─ factors               library + FactorEngine + IC 接口
    ├─ profit                利润断层（现主要用预告元数据，无财务报表序列）
    ├─ events                结构化事件标签
    ├─ candidate             漏斗 + 新闻重打分
    ├─ news.*                Provider 注册表 + engine
    ├─ ml.ranking            平台超额收益排序 + walk-forward + leakage detector
    ├─ ml.train              遗留月频 LGBM 特征（非产品默认选股）
    ├─ research.session      snapshot / council / debate / chair
    ├─ portfolio             仓位建议 + 开仓风控
    ├─ ai.client             OpenAI SDK 兼容
    ├─ ai.roundtable         四角色投委会
    ├─ ai.optimizer          改参，不读新闻
    ├─ backtest.engine       Strategy.on_date + T+1
    ├─ strategy.leader       回测用技术龙头代理（历史涨停接口不可复现）
    ├─ brokers               paper / qmt 壳
    └─ db                    schema.sql 交易表 + schema_research.sql + schema_news.sql
```

配置文件：`default.yaml`、`factors.yaml`、`research.yaml`、`news.yaml`、`prompts.yaml`、`models.yaml`、运行时 `agent_overrides.yaml`。

落盘：`data/reports/latest.json|md`、`data/research_snapshots/`、`data/news/raw_news.jsonl`、`data/paper_state.json`、`data/agent_state.json`。

前端三页：`web/src/pages/Overview.tsx`、`Research.tsx`、`Agent.tsx`。

---

## 6. 漏斗与权重（默认数字）

研究漏斗 `research.yaml`：

- `max_after_screen` 500（池侧已更小）
- `max_after_events` 100
- `max_research_pool` 20（拉新闻的上限）
- `max_council` 12（LLM 会话上限；`run_research` 再用 `top_n` 截断以省 token）

新闻重排权重 `news.yaml` `candidate_weights`：

- leader 0.35
- profit_inflection 0.25
- event 0.15
- news 0.15
- ml 0.10

粗排（拉新闻前）：`0.45*leader + 0.35*利润断层 + 0.20*事件`。利润质量 D 且事件分 < 0.3 直接丢掉。

Council 角色：fundamental、quant、event、valuation、bear + chair。`separate_trading_action: true`。

---

## 7. 数据缺口（评审时不要建议「直接算 PE」除非先接数据）

当前 **没有**：

- 按公告披露日对齐的财务时间序列（PE/PB/ROE/现金流）
- 行业/板块成分与行业指数 → 真·行业相对强度不可用
- 沪深300/中证500 等指数基准序列（超额收益/Alpha 不完整）
- 可历史复现的涨停/预告/新闻时间序列（故回测 `LeaderFactorStrategy` 只用技术因子代理）
- 分析师一致预期 → 新闻预期差模块恒为不可用，除非传入 actual/consensus

池子事件来自 AkShare 当日接口，**不能**当作历史事件数据库。

---

## 8. 遗留路径（不要和默认产品搞混）

| 口头说法 | 实际 |
|----------|------|
| `ml_lgbm_value` | **没有**这个 strategy 名。指 `strategy.name=ml_lgbm` + `picks_style=value` + `research.enabled=false`。此处 Value = 均线偏离均值回归，**不是估值** |
| `ml_lgbm` 回测 | 月频 Top-N，只用 LGBM 预测等权 |
| `anti_chase` | 防追高 + 上述均值回归合成 |
| `trade_review` | 默认关；`fetch_stock_news` 已是 NewsIntelligenceEngine 包装 |

回测 CLI：`python -m ashare.main backtest`，默认 `strategy.name=leader`。

---

## 9. 主要 API

`GET /api/health`  
`GET|POST /api/research/latest|run`  
`GET /api/research/sessions`  
`GET /api/news/{symbol}`  
`GET /api/factors`  
`GET /api/pnl` `/api/account` `/api/orders`  
`GET|POST /api/agent` start/stop/reset/cycle  
`POST /api/trade/picks` 模拟按最新 picks 下单  
`POST /api/backtest` `/api/train` 非主路径

---

## 10. 请外部模型重点审的问题（作者关心的）

1. 路径 A 与路径 B 双轨：平台 picks 覆盖遗留 picks 后，**模拟买入是否仍与「给人看的圆桌 buy」不一致**？会不会造成用户误解？
2. 新闻 15% 重排发生在已截断的 20 只之后，**新闻几乎不能把池外股票拉进研究**——这是否符合「机器找候选、新闻只当证据」？还是应该更早介入？
3. 优化器不看新闻、只调技术/池参数，与「新闻驱动研究」是否割裂？有没有更稳的闭环（例如用跟踪模块 outcome，而不是把标题喂给优化器）？
4. 主席 `SMALL_POSITION + BUY` 才允许模拟买：是否过严或过松？纸面资金 3000 与 `max_positions` 是否匹配？
5. 日频研究循环 30 分钟一次，盘中新闻会变，但 K 线仍是日线——产品定位是否应明确为「盘后研究」而非盘中交易？
6. 数据缺口下，valuation 角色与 Value 因子 `available=false`，AI 是否容易幻觉出基本面？prompt/payload 是否够硬？
7. 多源新闻实体关联偏弱时，错误新闻抬高 `news_score` 的风险。

---

## 11. 一句话架构图（文本）

```
AkShare(日线+涨停/预告) ──► 龙头/事件池 ──► 因子+利润断层+事件规则
                                      │
                                      ├─► Top-N ──► 四角色投委会（兼容）
                                      │
                                      └─► 漏斗20 ──► 多源新闻打分 ──► ML hint
                                                ──► 六角色Council+辩论+主席
                                                ──► 评级与交易动作分离
                                                      │
纸面账户 ◄── 仅 SMALL_POSITION∩BUY∩风控通过 才买 ◄──┘
    │
    └─► 优化器改因子/池阈值（不读新闻）──► 下一轮
```

人的位置：看 `data/reports` 与前端研报，决定是否当真；系统默认纸面，不路由实盘。
