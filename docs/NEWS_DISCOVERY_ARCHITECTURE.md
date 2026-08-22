# NEWS_DISCOVERY_ARCHITECTURE — Phase 0 代码审计（第三版）

> 日期：2026-08-22。**本文件只审计、不改业务代码。**  
> 原则：与代码冲突时以代码为准。文档（README / CURRENT_* / PROJECT_FOR_REVIEW）不得覆盖实现。  
> 目标：把 News 从「已有股票的评分器」升级为「并行发现引擎」；本阶段只回答怎么改、改哪里。

---

## 0. 结论（给实施用）

当前 News Intelligence **只能给已经进漏斗的股票打分**。  
硬截断发生在 `CandidateEngine.build_research_universe`：先按 Quant/Event/Profit 排到 `max_research_pool=20`，**然后才**对这 20 只调用 `NewsIntelligenceEngine.collect_stock`。

更窄的第二刀：`run_research` 把研究宇宙再切成 `strategy.top_n`（默认 **3**）才进 Council。`research.yaml` 的 `max_council=12` **没有被这条路径使用**。

不存在：`NewsOpportunityEngine`、`News → Stock` 全市场扫描、`candidate_sources`、`ResearchHypothesisEngine`、Price-In、按来源的 Alpha Attribution、行业/产业链图。  
`fetch_latest_news` 在 Provider 上已实现（新浪/同花顺），**引擎从未调用**。

最小改造：保留全部现有引擎；在漏斗 **截断之前** 并入 News Discovery；新闻失败不得拖垮 Quant 路径。

---

## A. 当前真实数据流

### A.1 研究一轮（产品默认）

```
agent.run_cycle / POST /api/research/run / python -m ashare.main research
    → services.picks.run_picks
         research.enabled=true 且 strategy≠dual_ma
    → services.research.run_research
```

`run_research`（`src/ashare/services/research.py`）实际做了 **两条轨**：

**轨 1 — 遗留投委会（先跑）**

```
build_leader_pool(cfg)                    # pool/builder.py
    AkShare: 涨停 / 强势 / 业绩预告 + 现货技术龙头补齐
    hard filter → pool.max_candidates 默认 40
ensure_panel(symbols)                     # data/provider.py  AkShare 日线
score_candidates(rows)                    # factors/score.py  8 因子，无新闻
shortlist = scored[:top_n]                # 默认 top_n=3
run_roundtable(shortlist)                 # ai/roundtable.py
    每只: news_package 或 NewsIntelligenceEngine.collect_stock
```

**轨 2 — 平台引擎（后跑，成功则覆盖 picks）**

```
CandidateEngine.build_research_universe(panel, pool=同一池)
    profit.enrich_candidates
    events.enrich_candidates              # 池标签 → EVENT_PRIORS，不是新闻抽取
    drop 利润质量 D 且 event_score<0.3
    [:max_after_events]                   # 默认 100
    FactorEngine.asof_rows
    粗排: 0.45*leader + 0.35*利润 + 0.20*事件
    research = scored[:max_research_pool] # 默认 20  ★新闻发现死于此
    仅对 research 每只 collect_stock      # Stock → News
    用 news_score 重排（新闻权重 0.15）
ResearchSessionEngine.run_pool(universe[:top_n], panel)
    MLRankingEngine.predict_rows          # 失败则跳过；发生在已截断名单上
    每只: snapshot → Council 五角色并行 → Debate → Chairman
RiskFilterEngine.allow_open
committee_approve =
    allow AND trading_action==SMALL_POSITION AND rating∈{BUY,STRONG_BUY}
PortfolioEngine.suggest_weights
```

轨 2 异常：`logger.warning` 后保留轨 1 的 picks。

### A.2 新闻调用链（代码入口）

| 调用点 | 文件 | 行为 |
|--------|------|------|
| 平台漏斗 | `candidate/__init__.py` L78–104 | **主路径**。只对截断后的 20 只 `collect_stock`；**不传 `as_of`** |
| 遗留圆桌 | `ai/roundtable.py` `_news_pkg` | 若候选已有 `news_package` 则复用，否则再 `collect_stock` |
| 兼容包装 | `ai/trade_review.py` `fetch_stock_news` | 引擎包装；`ai.trade_review` 默认 false |
| HTTP | `GET /api/news/{symbol}` | 任意代码拉个股新闻，与漏斗无关 |
| 引擎本体 | `news/engine.py` `collect_stock` | 见下 |

**`NewsIntelligenceEngine.collect_stock`（唯一标准化流水线）：**

```
providers.fetch_stock_news(symbol, name, limit=stock_limit=20)
    baidu / eastmoney / sina   （ths.stock 固定返回 []）
filter_asof(fetched, as_of)     # as_of 常为 None → 不过滤
dedupe_news                     # source_id / url / title_hash；本批次内
NewsStore.append                # 只写 data/news/raw_news.jsonl，不写 PG
for each news:
    link_entities(news, symbol=查询股, name)   # 永远绑回查询股
    classify_news                               # 关键词分类
    extract_events(..., relevance=link_conf)    # 关键词事件；无命中则 OTHER
    annotate_event                              # 质量/相关/时效
    expectation_gap()                           # 无参数 → available=false
net_event_score(events) → news_package
```

**不存在的引擎方法：** 无 `collect_market` / `discover` / `fetch_latest` 聚合。  
Provider 的 `fetch_latest_news`：`baidu` 返回 `[]`；`sina`/`ths` 有实现，**无调用方**。

### A.3 实体关联（`news/linking.py`）

输入必须带 **已有 `symbol`**。逻辑：

- 正文含公司名且含 6 位代码 → confidence 0.97 `title+code`
- 仅公司名 → 0.88 `title`
- 仅代码 → 0.82 `code`
- 都不含 → 仍输出该 symbol，confidence **0.35** `query_weak`

`NewsEntity.entity_type` 注释写了 `industry | theme`，**实现只产出 `stock`，且只有查询标的一个实体。**  
没有：全市场名称反查、别名表、行业受益股、`mapping_method=llm_inference`。  
名称缓存：`data/names.py` + `data/cache/stock_names.json`（研究时从池回填），**新闻发现未用**。

### A.4 事件抽取（`news/extract.py`）

规则表关键词 → `ORDER` / `EARNINGS_GUIDANCE` / `PRICE_INCREASE` / `CAPACITY_EXPANSION` / `M_AND_A` / `RESTRUCTURE` / `SHARE_BUYBACK` / `INSIDER_*` / `REGULATORY` / `LITIGATION` / `POLICY_SUPPORT`。  
无命中：强制一条 `OTHER`。  
`facts=[title]`，`inferences=[]`。无 `HYPOTHESIS` 字段。无跨稿件 Event Cluster。  
`EventEngine`（`events/__init__.py`）是 **池标签**（涨停/预增/技术龙头），与新闻抽取是两套类型名。

### A.5 `news_score`

`score.net_event_score`：过滤 `relevance>=0.5` 且非 OTHER；否则退回全部事件。  
加权：`Σ(direction_score * impact * relevance) / Σ(impact * relevance)`，截断 [-1,1]。  
漏斗重排（`news.yaml` `candidate_weights`）：

```
0.35*leader + 0.25*profit_inflection + 0.15*event + 0.15*news_score + 0.10*(ml*10)
```

此时 `ml_prediction` 通常仍为 0（ML 在 `run_pool` 才 `predict_rows`）。

### A.6 Candidate 排序与截断位置（代码行号）

| 截断 | 位置 | 默认 | 新闻之前？ |
|------|------|------|------------|
| 池规模 | `pool.max_candidates` | 40 | 是 |
| 事件后 | `funnel.max_after_events` | 100 | 是 |
| **研究池** | `funnel.max_research_pool` L43, L77 | **20** | **是（新闻死于此）** |
| Council | `run_research` `[:n]` n=`strategy.top_n` | **3** | 新闻已发生，但进不了 Council 的被静默丢掉 |
| yaml `max_council` | `research.yaml` 12 | **未被 run_research 引用** | — |

无 `max_news_candidates` / `max_union_candidates`。无 `reject_reason`。无 `candidate_sources`。

### A.7 AI Council payload（真实字段）

`research/council.py` `_call_role` 发给模型的 JSON：

```
symbol, name, quant, profit_inflection, event,
value_available, market_regime,
news_intelligence  ← news_package.role_views[role] 或整包
news_data_incomplete
```

**没有：** research_hypotheses、price_reaction、price_in_risk、candidate_sources、data_availability 总表、FACT/INFERENCE 分层（事件角色 prompt 要求了，抽取层没填 inferences）。

`ChairmanEngine.summarize` 的 payload **只有**：

```
snapshot_quant, opinions, debate, missing_roles
```

**主席看不到新闻包、假设、Price-In。** 只能看委员意见。启发式主席默认 `trading_action=WAIT_FOR_CONFIRMATION`，几乎进不了 `SMALL_POSITION`（模拟买的硬条件）。

Prompt：`config/prompts.yaml` 中 **`event_v1` 被缩进进 `quant_v1` 的 YAML 字面量**，因此 `roles.event_v1` **键不存在**。Council 加载 event 角色时落到 `"You are event. Output JSON."`。这是现码缺陷，第三版修 prompt 缩进即可，不必重写 Council。

### A.8 Snapshot

`research/snapshot.py` `build_snapshot`：research_id、quant 分项、profit_inflection、event（池事件）、market 价量、value/quality_available、market_regime、news_package、news_snapshot（ids+版本+incomplete）。  
落盘：`data/research_snapshots/{research_id}.json` + `data/research_sessions.jsonl`。  
PG `research_sessions` / `research_snapshots`：**init_schema 建表，研究主路径未 INSERT。**

### A.9 数据库（真实使用）

| Schema | 文件 | 运行时写入？ |
|--------|------|----------------|
| picks/orders/fills/... | `schema.sql` | 交易路径会写（若 PG 通） |
| research_sessions/snapshots/outcomes | `schema_research.sql` | **否**（文件 json/jsonl） |
| news / news_entities / news_events / news_provider_runs | `schema_news.sql` | **否**（仅 `raw_news.jsonl`） |

`research_outcomes` 表有 `research_id, symbol, horizon, actual/benchmark/excess, hit`。  
`TrackingEngine` / `ReviewEngine` / `news.outcome.event_outcomes` **没有任何 services 调用**（仅 export）。无按 `discovery_source` 分组。benchmark 常为 0 或 None。

### A.10 前端 Research 页

`web/src/pages/Research.tsx`：池节选、因子、圆桌、platform_reports 的 **新闻列表**（24h/7d、net_event_score、标题、timeline）。  
`web/src/api.ts` 有 `news(symbol)`，**页面未调用**。  
无 News Discovery 面板、无 hypothesis、无 Price-In、无 candidate_sources、无 reject_reason。

### A.11 优化器

`ai/optimizer.py`：输入模拟盘 metrics + 圆桌 summary；可改 top_n、池门槛、8 因子权重、LGBM retrain。  
**不读新闻正文，也不读 news_score / discovery 命中率。** 第三版应保持「学来源是否有效」，不要塞标题。

### A.12 回测

`backtest/engine.py` + `strategy/leader.py`：T+1，不用新闻。无历史新闻库。`news_factor` 不存在。

---

## B. 当前新闻为什么不能发现池外股票

因果链（全部是代码事实）：

1. **发现入口是股票代码，不是新闻流。** 只有 `fetch_stock_news(symbol)`。
2. **池外股票根本不会被查询。** 池来自涨停/强势/预告/技术龙头，上限 40。
3. **粗排后再截 20。** 第 21 名即使当天有重大订单，`collect_stock` 不会跑。
4. **关联函数不能从正文发现新代码。** `link_entities` 不扫描「其他股票」；弱匹配仍把新闻记在查询股上。
5. **没有行业/产业链映射模块。** 「材料涨价 → 受益股」在仓库中不存在。
6. **市场快讯未接入漏斗。** `fetch_latest_news` 闲置；`ths` 故意不返回个股以免错绑。
7. **Council 再砍到 top_n=3。** 即便 20 里有新闻强股，也可能进不了圆桌且无 reject_reason。

因此：News 是 **Candidate Ranking 的 15% 扰动**，不是 Discovery。

---

## C. 哪些代码可以直接复用

| 能力 | 复用对象 | 用法 |
|------|----------|------|
| 多源抓取 | `news/registry.py` + baidu/eastmoney/sina/ths | Discovery 调 `fetch_latest_news` + 保留 `fetch_stock_news` |
| 标准化 RawNews | `news/common.row_to_news`、`models.RawNews` | 不新造新闻对象 |
| 标题去重 | `news/dedup.py` | 第一层；Cluster 另加 |
| 关键词分类/抽取 | `classify.py` / `extract.py` | Discovery 事件骨架；禁止每条新闻 LLM |
| 质量/净分 | `score.py` `source_quality` `net_event_score` `annotate_event` | NewsCandidate 字段 |
| as_of 过滤 | `package.filter_asof` | 必须 **传入 as_of**；修「解析失败则放行」 |
| 个股包装 | `collect_stock` + `build_package` | Stock→News 保留给 Union 后验证 |
| 名称反查 | `data/names.py` | News→Stock 规则层 2–4 |
| 池/利润/事件/因子/ML | 现有四个引擎 | Union 后验证，不删除 |
| 会话/Council/风控/纸面 | session/council/portfolio/paper | 不改成交与 T+1 |
| Outcome 骨架 | `tracking.py` + `news/outcome.py` + PG `research_outcomes` | 补 `discovery_source` |
| 前端新闻块 | Research.tsx platform_reports.news | 扩成 Discovery 面板，不另起站点 |

不复用为 Discovery 的：`link_entities` 的「查询股强制绑定」——可并列新函数 `link_entities_open(news, name_map)`，旧函数留给 Stock→News。

---

## D. 最小改造方案（不重写）

1. **新增** `NewsOpportunityEngine`：扫 latest（sina/ths）+ 可选关键词；规则抽取事件；规则映射股票；产出 `NewsCandidate` + `reject_reason`。失败返回空列表。
2. **扩展** `CandidateEngine`：Quant/Event/Profit 名单 **与** NewsCandidates **Union → dedup → hard filter → max_union_candidates(100) → 统一排序 → max_research_pool(20)**。新闻拉取挪到 Union 之后做验证（Stock→News 保留）。
3. **配置** `research.yaml` / `news.yaml` 增加 `max_news_candidates=100`、`max_union_candidates=100`；`max_research_pool=20` 改为 **排序后** 截断。Council 截断改用 `max_council`（12）或显式配置，避免误用 `top_n=3` 作为发现上限（`top_n` 仍可限制模拟买入只数）。
4. **每条候选** 写 `candidate_sources: list[str]`。
5. **Hypothesis / Price-In / Attribution / 前端 / 测试** 按 Phase 4–9 叠加；Phase 1 不改 Broker、不改回测成交、不提高 news 权重到 30%+。

Industry→受益股：无图则 `available=false`，只做 **代码/全称/简称** 命中；LLM 映射必须 `mapping_method=llm_inference` 且低置信 + 默认识别为非高置信候选。

---

## E. 新模块应放在哪里

| 模块 | 建议路径 | 说明 |
|------|----------|------|
| NewsOpportunityEngine | `src/ashare/news/opportunity.py` | 复用 engine/providers，不替换 `NewsIntelligenceEngine` |
| News→Stock 开放关联 | `src/ashare/news/linking.py` 新增函数 | 保留旧 `link_entities` |
| Event cluster / novelty | `src/ashare/news/cluster.py` | 标题规范化已有 |
| ResearchHypothesisEngine | `src/ashare/research/hypothesis.py` | 规则模板为主，LLM 仅高不确定 |
| Price reaction | `src/ashare/research/price_reaction.py` | 只用 panel 日线；无 bar → available=false |
| Intelligence package | `src/ashare/research/intel_package.py` 或扩展 `build_snapshot` | 给 Council 用 |
| Candidate Union | `CandidateEngine.build_research_universe` 内扩展 | 不新引擎类也可 |
| Attribution | 扩展 `tracking.ReviewEngine` | 按 sources 分组 |
| 静态映射（可选、后期） | `config/industry_map.yaml` | 没有可靠数据就不要造 |

---

## F. 数据库变更方案

**先复用，少建表。**

已有可复用：

- `news` / `news_entities` / `news_events`：主路径改为可选 INSERT（现只 jsonl）。
- `research_outcomes`：增加 **可空** `discovery_sources TEXT` 或 JSONB（现无此列，需 ALTER）。
- `research_snapshots.snapshot_json`：可塞 hypotheses / news_candidates，不必先拆表。

建议 **新增**（仅当 JSON 查询不够时）：

```
news_candidates (
  id, as_of, symbol, candidate_source, event_id, event_type,
  direction, impact, relevance, novelty, source_quality, confidence,
  mapping_method, time_horizon, price_in_risk, reject_reason, status,
  evidence_ids JSONB, payload JSONB
)
research_hypotheses (
  id, research_id, symbol, event_id, type, statement,
  validation_questions JSONB, evidence_ids JSONB
)
```

不要复制 `news_events` 已有字段。没有历史事件库时 **不要** 建假的 hit_rate 表并填数；`HistoricalEventOutcome` 可先文件 + `available=false`。

---

## G. API 变更方案

现有：`GET /api/news/{symbol}`、`GET /api/research/latest|sessions|session/{id}`。

新增（均支持 `as_of, symbol, event_type, candidate_source, status` 查询参数，无数据返回空列表 + available 标记）：

| 方法 | 路径 | 数据来源（建议） |
|------|------|------------------|
| GET | `/api/news/discovery` | 最近一次 cycle 的 NewsCandidate 列表 |
| GET | `/api/news/events` | 抽取/聚类后的事件 |
| GET | `/api/research/candidates` | Union 后名单（含 sources、reject） |
| GET | `/api/research/candidates/{symbol}` | 单只 |
| GET | `/api/research/hypotheses` | 假设列表 |
| GET | `/api/research/outcomes` | TrackingEngine 结果 |
| GET | `/api/research/attribution` | 按 discovery_source 汇总 |

注意：FastAPI 路由须把 `/api/news/discovery` 写在 `/api/news/{symbol}` **之前**，否则 `discovery` 会被当成 symbol。

---

## H. 前端变更方案

`Research.tsx` 增加 **News Discovery** 面板（规格 §二十一/三十二），字段：symbol、事件、方向、impact、novelty、confidence、source quality、candidate_sources、hypothesis、price reaction、price-in risk、是否进 Council、reject_reason。  
现有「新闻与事件」列表保留给已进 Council 的标的。  
不把 Discovery 做成纯标题流。

---

## I. 测试方案（必须新增）

现有 `tests/test_news_intelligence.py`：去重、弱关联、分类抽取、预期差、净分、未来新闻 `filter_asof`、registry。  
**缺口：** Union、来源归因、假设、Price-In、Council payload、reject、attribution。

第三版至少：

1. News → Stock Entity（代码/全称命中；无命中不高置信）  
2. Event Dedup / Cluster（10 条转载 → 1 事件）  
3. NewsCandidate 生成（不产生 BUY）  
4. Candidate Union  
5. `candidate_sources`  
6. Hypothesis `type=HYPOTHESIS`  
7. Price reaction（有 bar）  
8. Price-In 只警告不改交易动作  
9. As-of leakage  
10. **未来新闻：as_of=2026-08-20，published_at=2026-08-21 → 不可用**（现 `filter_asof` 在解析失败时会 **放行**，必须先修此行为再测）  
11. Duplicate news  
12. Council payload 含 intelligence package / available=false  
13. Reject reason  
14. Outcome 按 source 归因  

禁止网络测试作为必过项；Provider 用 fixture。

---

## J. 如何避免未来数据泄漏

**已有：** `filter_asof`；回测不用新闻。

**现码漏洞：**

| 点 | 代码 | 风险 |
|----|------|------|
| `collect_stock` 未传 as_of | `candidate/__init__.py` | 实时研究混入「未来」相对历史 as_of |
| `published_at` 解析失败仍保留 | `package.filter_asof` | 无日期新闻进入研究 |
| 时效用 `datetime.now` | `score.freshness_score`、`build_package` 分桶 | 回放研究时用「今天」当 as_of |
| 无 `available_at` 字段 | `RawNews` | 无法区分刊登日与可交易日 |
| 指数超额 | `event_outcomes` excess=None | 不要假装有 Alpha |

**第三版硬规则：**

- 所有研究入口传 `as_of`；`ts > as_of` 丢弃。  
- 解析失败 → **丢弃或 `available=false`，禁止默认放行。**  
- 新鲜度/分桶相对 `as_of`，不用墙钟（除非 as_of=now 的实时模式）。  
- 实时 Discovery 与历史 Backtest 分开关；无历史新闻则回测 `news_discovery.available=false`，禁止用今日 jsonl 回填。

---

## 1. 当前新闻完整调用链

见 §A.2。一句话：`fetch_stock_news(已有代码)` → 标准化 → 绑回该代码 → `news_score`。

## 2. 当前 Candidate 完整调用链

见 §A.1 轨 2。一句话：池40 → 利润/事件标签 → 截100 → 因子粗排 → **截20** → 新闻重排 → **再截 top_n=3** → Council。

## 3. 池外不可达

见 §B。

## 4. 最小修改

见 §D。

## 5. 新增模块列表

见 §E。

## 6. 修改文件列表（后续 Phase，本阶段不改）

**新增：**

- `src/ashare/news/opportunity.py`
- `src/ashare/news/cluster.py`
- `src/ashare/research/hypothesis.py`
- `src/ashare/research/price_reaction.py`
- `src/ashare/research/intel_package.py`（或并入 snapshot）
- `src/ashare/db/schema_news_discovery.sql`（或 ALTER 进 schema_news/research）
- `tests/test_news_discovery.py`（及 union/hypothesis/price/asof）
- `docs/NEWS_DISCOVERY_ARCHITECTURE.md`（本文件，Phase 0 已写）

**修改（扩展，禁止删除类）：**

- `src/ashare/candidate/__init__.py` — Union + 截断顺序
- `src/ashare/news/engine.py` — `collect_latest`；`collect_stock` 传 as_of
- `src/ashare/news/linking.py` — 开放映射函数
- `src/ashare/news/package.py` — 解析失败不放行；分桶用 as_of
- `src/ashare/news/score.py` — freshness 相对 as_of
- `src/ashare/news/models.py` — 可选 `available_at`；Candidate 结构可用 dataclass 新文件
- `src/ashare/research/snapshot.py` / `council.py` / `session.py` — intelligence package；主席 payload
- `src/ashare/services/research.py` — Council 用 `max_council`；写出 sources
- `src/ashare/research/tracking.py` — attribution by source
- `src/ashare/api/app.py` — 新路由顺序
- `src/ashare/ai/optimizer.py` — 只加来源命中率指标，不喂正文
- `config/research.yaml` / `config/news.yaml`
- `config/prompts.yaml` — **修正 event_v1 缩进**（兼容修复）
- `web/src/pages/Research.tsx` / `web/src/api.ts`

**禁止修改：** `brokers/paper.py` 成交核心、`backtest/engine.py` T+1 规则、删除现有 Engine 类。

## 7–10. 库 / API / 前端 / 测试

见 §F–I。

## 11. 数据泄漏风险

见 §J。另：Sina 关键词个股新闻可能夹带无关稿；弱关联 0.35 仍进入 `net_event_score` 的 fallback（无高相关事件时用全部事件）。Discovery 必须设 **最低 confidence 门槛**，否则垃圾新闻会把池外噪声送进 Union。

## 12. 性能风险

当前：最多约 20 次 `collect_stock` × 3 Provider × HTTP。  
若对全市场每条快讯 LLM：不可接受。  
Discovery 必须：规则抽取 → 名称反查 → 仅高不确定产业链才 LLM。  
`max_news_candidates=100` 限制。latest 接口分页要限页。  
Union 后 Stock→News 仍按 20 只拉，避免 100 只全拉三源。

## 13. 兼容性风险

- 轨 1 圆桌仍按 top_n 拉新闻：行为可保留。  
- picks 被轨 2 覆盖：需在 payload 同时露出 `news_candidates` / `rejected`，避免「突然消失」。  
- 启发式主席几乎不下 `SMALL_POSITION`：Discovery 增加候选 **不会自动增加成交**（符合「新闻≠BUY」）。  
- PG 未写 news 表：文件 jsonl 仍是真相源，新 API 先读内存/上次 cycle 落盘。  
- `prompts.yaml` event 键缺失：修缩进可能改变 event 角色质量，属修复非破坏。

## 14. 分 Phase 实施计划

| Phase | 内容 | 完成标准 | 本阶段改代码？ |
|-------|------|----------|----------------|
| **0** | 本审计文档 | 调用链与截断点有文件行号 | **否（已完成）** |
| **1** | NewsOpportunityEngine + latest 抓取 + 规则事件 | 无 symbol 输入也能产出事件列表；失败降级 | **是（已完成）** |
| **2** | News→Stock（代码/名称；LLM 低置信标记） | 池外代码可出现在 NewsCandidate | **是（已完成）** |
| **3** | Candidate Union + sources + reject_reason + 配置截断 | 池外新闻股可进 20；有 reject 日志 | **是（已完成）** |
| **4** | ResearchHypothesisEngine | FACT/INFERENCE/HYPOTHESIS 分层 | **是（已完成）** |
| **5** | Research Intelligence Package + Council/主席 payload + 修 prompt | available=false 传到模型 | **是（已完成）** |
| 6 | Price reaction / price_in_risk（警告 only） | 大涨不自动 PASS | 是 |
| 7 | Outcome + attribution by source | 能回答新闻发现有无收益；样本不足 available=false | 是 |
| 8 | Frontend News Discovery | 规格卡片字段齐全 | 是 |
| 9 | 测试清单 §I | 含未来新闻拒绝 | 是 |
| 10 | 跑一轮 research cycle 人工验收 | 同时出现 quant/news/event/profit sources | 是 |

每 Phase 结束：跑现有 `tests/test_news_intelligence.py` + `tests/test_platform_engines.py`；列出 diff 文件；更新本文件「已落地」小节（到时再写）。

---

## 附录：明确不存在的模块（禁止脑补）

已落地（Phase 1–5）：News 发现与映射、Candidate Union、Hypothesis、`build_research_intelligence`、Council/主席 payload、`event_v1` prompt 修复。

仍不存在：

- Price-In 计算 / 按来源 Alpha Attribution
- 行业成分、供应链图、一致预期、指数基准序列
- HistoricalEventOutcome 统计库
- novelty_score 可用 / price_in_risk 计算
- PG 新闻/研究表的运行时写入
- TrackingEngine 接入 agent/research
- Optimizer 的新闻来源评估
- 行业/产业链受益股图（无数据，行业新闻 → INDUSTRY_MAP_UNAVAILABLE）

行业/政策「受益股」若无映射数据：输出事件 + `mapping_status=unavailable`，而不是 LLM 点名一串高置信股票。

---

## Phase 1 落地（2026-08-22）

**数据流（新增，不改漏斗截断）：**

```
run_research
  → NewsOpportunityEngine.discover(as_of=日线日 23:59 UTC)
       collect_latest(sina, ths)   # 失败降级，不中断研究
       filter_asof（无日期则丢弃）
       关键词抽取 ExtractedEvent
       正文 6 位代码 → NewsCandidate(mapping_method=code)
       无代码 → rejected NOT_ENOUGH_EVIDENCE
  → payload.news_discovery（不进入 CandidateEngine 20 只）
  → data/news/discovery_latest.json
```

**修改文件：** `news/models.py` `news/engine.py` `news/linking.py` `news/package.py` `news/opportunity.py` `news/__init__.py` `config/news.yaml` `services/research.py` `api/app.py` `tests/test_news_discovery.py` `tests/test_news_intelligence.py`

**风险：** 仅代码命中会进 NewsCandidate；无代码的重大行业新闻仍被拒绝。Discovery **尚未**把池外股送进 Council。漏斗 20 截断未动。

**下一阶段：** Phase 5 Research Intelligence Package。

---

## Phase 5 落地（2026-08-22）

`build_research_intelligence` 打包：quant / profit / event / news / hypotheses / candidate_sources / data_availability / evidence_ids。  
`available=false`（估值、一致预期、行业图、Price-In 等）明确下传。  
Council 各角色与 Chairman 均接收该包；禁止因新闻重大单独 BUY。  
修复 `config/prompts.yaml` 中 `event_v1` 被缩进进 `quant_v1` 的问题。

**修改文件：** `research/intel_package.py` `snapshot.py` `council.py` `session.py` `config/prompts.yaml` `news/opportunity.py`（惰性 import）`tests/test_intel_package.py`

**风险：** LLM 仍可能忽略 available=false；靠 prompt + payload 双重约束。

**下一阶段：** Phase 6 用日线计算 price_reaction / price_in_risk（仅警告）。

---

## Phase 6 落地（2026-08-22）

`research/price_reaction.py`：用 panel 日线分离 `news_signal` 与 `price_signal`，输出 `price_in_risk`（HIGH/MEDIUM/LOW/UNKNOWN）。  
无 K 线 → `available=false`，不伪造。  
**仅警告**：HIGH 不自动 PASS/SELL、不改 `trading_action`、不因 Price-In 拒绝候选。

挂载点：`CandidateEngine` 合并 NewsCandidate 时、`run_research` 补齐 K 线后标注 discovery、`snapshot` / intel package 下传 Council。

**修改文件：** `research/price_reaction.py` `candidate/__init__.py` `services/research.py` `snapshot.py` `intel_package.py` `news/opportunity.py` `tests/test_price_reaction.py`

**风险：** 事件日解析依赖 `published_at`/`event_time`；缺失则用最新 bar，可能略偏。

**下一阶段：** Phase 7 Outcome Attribution by source。

---

## Phase 7 落地（2026-08-22）

`TrackingEngine` 产出带 `candidate_sources` / `source_bucket`（news_only / quant_only / news_plus_quant）的 outcome。  
无真实基准时 `excess_return=null`（不再用 0 假装超额）。  
`ReviewEngine.summarize_by_source` / `attribution_report` 按来源汇总胜率与收益；**只描述、不改权重/交易动作**。  
`run_research` 写入 `research_outcomes` 与 `data/research_outcomes.json`；API：`GET /api/research/outcomes`、`GET /api/research/attribution`。  
schema 增加可空 `discovery_sources`。

**修改文件：** `research/tracking.py` `services/research.py` `api/app.py` `config/research.yaml` `db/schema_research.sql` `tests/test_attribution.py`

**风险：** 当日研究多数 horizon 仍为 pending；归因样本要等交易日推进。勿把 source win-rate 当自动买卖信号。

**下一阶段：** Phase 8 Frontend News Discovery 面板。

---

## Phase 8 落地（2026-08-22）

`Research.tsx` 增加 **News Discovery** 面板：symbol / 事件 / 方向 / impact / novelty / confidence / 源质 / 映射 / Price-In / 价讯·价动 / 假设 / 是否进 Council / reject。  
保留平台研报内「新闻与事件」块。附带来源归因摘要（描述性）。`api.ts` 增加 discovery / candidates / hypotheses / outcomes / attribution 客户端方法。

**修改文件：** `web/src/pages/Research.tsx` `web/src/api.ts`

**下一阶段：** Phase 9 补齐测试缺口；Phase 10 实盘研究一轮验证。

---

## Phase 9 落地（2026-08-22）

第三版验收清单 1–14 用离线 fixture 覆盖（`tests/test_news_discovery_v3_checklist.py`）：实体映射、转载去重、NewsCandidate 不产 BUY、Union/`candidate_sources`、Hypothesis、Price-In 警告、as-of/未来新闻/无日期丢弃、Council intel `available=false`、reject、按来源归因。  
Discovery 路径补 `dedupe_news`（注入与抓取后均去重）。

**修改文件：** `news/opportunity.py` `tests/test_news_discovery_v3_checklist.py`

---

## Phase 10 落地（2026-08-22）

离线研究循环契约测试（`tests/test_phase10_research_cycle.py`）：discovery → union → heuristic Council → outcomes/attribution；断言新闻不产生 BUY/SMALL_POSITION，归因不改交易动作。不连券商、不依赖外网 Provider。

**联调：** 重启 API 后路由可用（`/api/news/discovery`、`candidates`、`hypotheses`、`outcomes`、`attribution`）。  
同日 agent 循环已写出 `data/news/discovery_latest.json`（sina/ths ok，本轮 `n_candidates=0`、行业/无代码新闻进 rejected——符合「无映射不高置信」）。完整 `latest.json` 需等 Council LLM 跑完才覆盖。

**修改文件：** `tests/test_phase10_research_cycle.py`

---

## Phase 4 落地（2026-08-22）

规则模板把事件写成三层：`FACT`（标题原句）/ `INFERENCE`（可能如何影响经营）/ `HYPOTHESIS`（带验证问题）。`type` 恒为 `HYPOTHESIS`，禁止把假设写成事实。不调 LLM，不产出 BUY。

挂在 NewsCandidate、Union 行、snapshot、`GET /api/research/hypotheses`。

**修改文件：** `research/hypothesis.py` `news/opportunity.py` `news/models.py` `candidate/__init__.py` `snapshot.py` `session.py` `services/research.py` `api/app.py` `tests/test_hypothesis.py`

**风险：** 模板是通用句，不是公司特定财务；无营收占比数据时问题保持 unanswered。

**下一阶段：** Phase 5 Research Intelligence Package（已完成）→ Phase 6 Price Reaction。

---

## Phase 3 落地（2026-08-22）

漏斗改为：池 Quant/Event/Profit 与 NewsCandidate **并行合并** → 去重 → `max_union_candidates=100` → 统一打分 → **`max_research_pool=20` 之后才** `collect_stock`。Council 用 `max_council`（12），不再用 `top_n=3` 砍研究名单。

无 K 线：`FACTOR_VALIDATION_FAIL`。进不了 20：`RANKING_CUTOFF`。新闻≠BUY。

**修改文件：** `candidate/__init__.py` `config/research.yaml` `services/research.py` `research/snapshot.py` `research/session.py` `api/app.py` `tests/test_candidate_union.py`

**风险：** 新闻独有标的会触发额外 AkShare 拉数；名称表漏映射的仍进不了 Union。

**下一阶段：** Phase 4 研究假设分层。

---

## Phase 2 落地（2026-08-22）

**News → Stock 规则优先级（无 LLM 热路径）：** 代码 → 官方全称（`stock_names.json` + STATIC_NAMES）→ `news.yaml` aliases。  
`llm_inference_entities` 置信度硬顶 0.45，且 **不进入** `news_candidates`（记入 rejected / `LOW_CONFIDENCE`）。默认 `llm_mapping: false`，研究循环不调模型做映射。

无标的且标题含「行业」或 POLICY：`INDUSTRY_MAP_UNAVAILABLE`。

**修改文件：** `news/linking.py` `news/opportunity.py` `news/models.py` `config/news.yaml` `tests/test_news_discovery.py`

**风险：** 名称表不全则漏映射；过短词（银行/中国）已跳过。仍未 Union。

**下一阶段：** Phase 3 Candidate Union。
