# CURRENT_NEWS_ARCHITECTURE — 新闻 / 公告 / 事件情报（现状）

> 2026-08-22 更新：新闻**不绑定东方财富**。引擎按 `config/news.yaml` 的 `providers` 顺序拉取，单源失败降级。

**个股：** 百度股市通（聚合同花顺/东财/证券时报等原文链接）+ 东财搜索 + 新浪滚动关键词。  
**全市场 7x24：** 同花顺快讯（`ths`，不当作个股新闻，避免错绑标的）。  
雪球有 WAF、财联社/腾讯部分接口已失效，未接入。

---

## 0. Phase 1 扫描原文（已过时，仅作对照）

当时仓库**没有独立的 News Intelligence Engine**。新闻只有一条临时抓取函数：东方财富搜索最近 5 条标题/摘要，塞进**旧圆桌 / 旧交易审查**的 LLM payload。新平台 Event Engine **不读新闻**；新 Council / Snapshot / 前端 **都不展示、不持久化新闻**。

---

## 1. 当前新闻数据来源（实现后）

| 来源 | 配置名 | 用途 |
|------|--------|------|
| 百度股市通 | `baidu` | 个股新闻，带第三方原文 URL |
| 东方财富搜索 | `eastmoney` | 个股 CMS 标题/摘要 |
| 新浪财经滚动 | `sina` | 关键词检索（公司名/代码） |
| 同花顺 7x24 | `ths` | **仅全市场快讯**，不绑个股 |
| AkShare 涨停/强势/预告 | （池，非新闻引擎） | 行情事件池 |
| 上交所/深交所公告原文 | — | **未接** |
| 雪球 / 财联社 / 腾讯部分接口 | — | WAF 或接口失效，**未接** |
| 东财 PC 终端 `dfcf` 本地 `.dat` | — | **不读**（无官方 SDK） |

实现入口：[`src/ashare/news/`](src/ashare/news/) + [`config/news.yaml`](config/news.yaml)。  
`trade_review.fetch_stock_news` 已是引擎包装，不再单独绑东财。

AkShare 依赖里存在 `stock_notice.py`（公告大全），**本项目未调用**。

---

## 2. 当前抓取方式

唯一实现：[`src/ashare/ai/trade_review.py`](src/ashare/ai/trade_review.py) `fetch_stock_news(symbol, limit=5~6)`。

- **关键词**：`bare_code(symbol)`（6 位代码，不是公司名）
- **类型**：`cmsArticleWebOld`
- **协议**：HTTP JSONP，解析 `jQuery({...})`
- **失败**：catch 后返回 `[]`，打 warning
- **无**：Provider 接口、重试策略、全市场缓存、盘前/盘中调度
- **耦合**：抓取函数写在 `trade_review.py`，被 `roundtable.py` 直接 import

```
keyword=600000
  → Eastmoney search JSONP
  → result.cmsArticleWebOld[:limit]
  → {date, title, summary[:180], media}
```

---

## 3. 当前数据结构

内存 dict，无 schema / 无 id：

```
{
  "date": str,       # 搜索结果里的 date，格式未规范化
  "title": str,      # 去掉 <em>
  "summary": str,    # content 截断 180 字，非全文
  "media": str       # mediaName
}
```

**缺失字段：** `url`, `source_id`, `content` 全文, `fetched_at`, `author`, `raw_payload`, `category`, 实体关联, 相关性, 事件类型。

---

## 4. 新闻在哪里进入 LLM

### A. 旧圆桌（产品研究默认仍会跑）

[`ai/roundtable.py`](src/ashare/ai/roundtable.py) `build_roundtable_payload`：

```
candidates[].news = fetch_stock_news(sym, limit=5)
```

整包 `candidates`（含 news）JSON dump 给 dragon / event / risk；主席看到委员意见，**不单独再拉新闻**。  
`run_roundtable` 返回的 `payload_preview` 含 `news_titles` 最多 3 条。

### B. 旧交易审查（默认关闭）

[`config/default.yaml`](config/default.yaml) `ai.trade_review: false`。  
若打开：[`trade_review.py`](src/ashare/ai/trade_review.py) 同样 `limit=5` 塞进审查 prompt。

### C. 新 6 角色 Council（**不进新闻**）

[`research/council.py`](src/ashare/research/council.py) payload 仅有：

`symbol, name, quant, profit_inflection, event, value_available, market_regime`

`event` 来自股票池标签规则分，**不是新闻抽取**。  
Event Analyst prompt 写的是 “Score catalysts from structured events only.”

---

## 5. 哪些 AI Role 使用新闻

| 角色 | 是否看到新闻 |
|------|----------------|
| 旧 dragon / event / risk | 是（同一份 5 条列表，无分角色裁剪） |
| 旧 chair | 间接（委员文本），无独立 News Package |
| 新 fundamental / quant / event / valuation / bear / chair | **否** |
| 空头 Blind Review | 未实现（新 Council 并行，bear 看不到别人结论，但也看不到新闻） |

---

## 6. Event Engine 如何使用新闻

**完全不用新闻。**

[`events/__init__.py`](src/ashare/events/__init__.py) 从池 meta 映射：

- `sources`: limit_up / strong / tech_leader / profit_gap
- `event_tags` / `forecast_type`
- 规则先验 `EVENT_PRIORS`（涨停 +0.4、预增 +0.7、减持 -0.5 …）

输出 `MarketEvent`：`event_type, event_time, source, direction, impact_score, confidence, description, symbol`。

无 URL、无 evidence_id、无 expectation_gap、无 T+N 价格复盘。

---

## 7. 前端是否展示新闻

[`web/src`](web/src) **零处**匹配 `news`。  
Research 页：池标签、因子、圆桌、`platform_reports`。  
`payload_preview.news_titles` **未接到 UI**。

---

## 8–12. 持久化 / 去重 / 时间戳 / 来源 / 股票关联

| 能力 | 现状 |
|------|------|
| 持久化 | **无** news 表。PG：`picks/orders/...` + `research_sessions/snapshots/outcomes`（无 news_*）。磁盘 snapshot **不含 news** |
| 去重 | **无**（每次研究即时抓） |
| 时间戳 | 搜索 `date` 字符串；无 `fetched_at`；无法保证可解析 |
| 来源 | `media` 媒体名；无 URL；无 A/B/C/D 源质量 |
| 股票关联 | **默认整次搜索都属于当前代码**；无 confidence；代码关键词易误伤同名/同数字 |

---

## 13. 当前问题清单

1. 条数少（5），无 24h/7d/30d 包  
2. 无独立模块，耦合 `trade_review`  
3. 无结构化分类 / 事件抽取  
4. 无存储、无去重、无缓存 → 每只股票重复请求  
5. 无相关性 / 源质量 / freshness / priority  
6. 无公告原文、无政策源  
7. 无实体链接（行业/主题/上下游）  
8. 无 Expectation Gap（禁止假装一致预期）  
9. 无 Event Outcome / 历史 Alpha  
10. 新旧路径分裂：旧圆桌有新闻，新 Council 没有  
11. 前端无法点证据  
12. AI 无法引用 evidence_id；FACT/INFERENCE/OPINION 未区分  
13. 搜索失败静默变空列表，session 不标记 `news_data_incomplete`  
14. 标题党 / 同代码误匹配无校验  

---

## 14. 模块对照

```
旧路径:  fetch_stock_news → roundtable payload.news → LLM（全角色同一列表）
新路径:  pool tags → EventEngine 规则分 → snapshot.event → Council（无新闻）
前端:    不展示 news
DB:      无 news 表
```

---

## 15. 可复用 vs 应重构 / 删除

**可复用（薄封装进 Provider）**

- `fetch_stock_news` 的东财 JSONP 解析（作 `EastMoneyProvider.fetch_stock_news` 雏形）
- `bare_code` / `to_symbol`
- `EventEngine.MarketEvent` + `EVENT_PRIORS`（扩展 schema，勿当新闻抽取）
- `pool/events.py` 业绩预告/涨停（**事件源**，不是 News）
- Snapshot / Council / Research 页骨架
- AkShare `stock_notice`（未接，可作 AnnouncementProvider 候选）
- `research_snapshots` 文件落盘模式

**应重构**

- 从 `trade_review.py` 抽出 Provider  
- 旧圆桌停止「5 条原文塞 prompt」→ News Intelligence Package  
- 新 Council payload 接入 package（分角色视图）  
- Snapshot + 前端证据链  
- EventEngine：新闻抽取事件 ∪ 池规则事件，去重合并  

**不要删除（先保留兼容）**

- `fetch_stock_news` 可暂留 wrapper，内部改走 Provider  
- 旧 `trade_review`（默认关）  
- 现有 `EventEngine` 规则路径  

**不要做**

- 把东财写死进 `ResearchSessionEngine`  
- 伪造一致预期 / 伪造公告全文  

---

## 16. 推荐实施顺序（确认后再动手）

与需求 Phase 2–15 对齐：

1. **NewsProvider 接口** + EastMoneyProvider（失败 → `PROVIDER_UNAVAILABLE`）  
2. **Raw News 存储**（文件或新增 `news` 表，不破坏现有表）+ 全局 cache  
3. **Dedup**（URL + 规范化 title hash）  
4. **Entity linking + relevance**（禁止默认 100% 属于搜索代码）  
5. **Classification + Event Extraction**（规则先，LLM 可选且必须 evidence_id）  
6. **Scoring + Expectation Gap**（无一致预期则 confidence 降低，不编造）  
7. **Council 分角色 News Package** + Snapshot `news_snapshot`  
8. **前端：新闻列表 / 时间线 / 点开证据**  
9. **Event Outcome T+1…T+20** + 日后 Event Alpha（数据不足不伪造）  

---

## 17. Phase 1 验收

- [x] 定位 `fetch_stock_news` 与全部 news 入口  
- [x] 旧/新 Council、Event Engine、Snapshot、前端、DB 已对照  
- [x] 13 问可在对话中回答  
- [x] **业务代码零修改**（仅本文件）
