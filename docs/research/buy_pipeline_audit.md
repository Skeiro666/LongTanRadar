# LongTanRadar BUY Pipeline + Weak-News Strong-Quant Failure Audit

**As-of:** 2026-08-24  
**Reports analyzed:** 3  

## Data limitations

- **trading_days_in_production_cycles:** 6
- **outcome_records:** 80
- **forward_bars_note:** T+N returns limited by parquet cache end date; refresh attempted
- **requested_windows_20_40_60:** insufficient calendar history — using all available cycles

## 1. BUY Funnel (latest cycle)

| Layer | In | Out | Reject | Reject reason |
|---|---:|---:|---:|---|
| Universe (market screen) | 2337 | 780 | 1557 | screen_filters |
| Pool | 780 | 60 | 720 | pool_cap_and_rank |
| News discovery | 42 | 0 | 42 | NOT_ENOUGH_EVIDENCE / mapping fail |
| Candidate Union | 60 | 20 | 80 | union_rank_cap_20 |
| Research Gate | 20 | 10 | 10 | DEEP_BUDGET:10 |
| Council (LLM/heuristic) | 10 | 20 | 0 | none |
| Chairman rating | 20 | 7 | 13 | WATCH:7, AVOID:1, GATE_SKIP:12 |
| Trading Action (SMALL_POSITION required) | 7 | 0 | 7 | WAIT_FOR_CONFIRMATION:6, NO_ACTION:14 |
| Risk Filter | 8 | 2 | 6 | ('limit_up',):6 |
| Final BUY (committee_approve) | 0 | 0 | 20 | rating×action×risk compound gate |

## 2. Zero BUY analysis

- Production cycles: **6** (dates: ['2026-08-21', '2026-08-24'])
- Total BUY across cycles: **0** → BUY_RATE = **0.00%**
- Latest: candidates=60, council=20, BUY rating=0, SMALL_POSITION=0, final BUY=0
- Historical council BUY sessions (research_sessions.jsonl): **5**

**Bottleneck (evidence-based):**
1. **Trading Action gate** — 0× `SMALL_POSITION`; council outputs `WAIT_FOR_CONFIRMATION` or `NO_ACTION`.
2. **Council rating** — 0× `BUY`/`STRONG_BUY` in canonical on latest cycle (mostly `WATCH`/`AVOID`/`GATE_SKIP`).
3. **Risk filter** — 6/8 focus stocks blocked on `limit_up` (T-day close at limit-up → cannot open).
4. **Research gate** — `DEEP_BUDGET` rejected 10/20 research-pool names before council.

## 3. Quant-only vs Quant+AI

### quant_only (n=31)
- T+1: mean=-0.41%, win=33.3%, n=27
- Profit factor (T+5): None
- Mean max drawdown: 0.0

### quant_plus_ai (n=1)
- Profit factor (T+5): None
- Mean max drawdown: None

## 4. Weak News + Strong Quant bucket

- n=2, T+5 mean=None

## 5. Four quadrants (T+5 mean)


## 6–7. Strong Quant + Weak News — stage


## 8. Chase score (research-only)

Computed from `anti_chase.chase_penalty` — not in production BUY path.

## 9. Negative evidence (chairman risk text)

- risk_warning: 2
- abnormal_volatility: 8
- performance_miss: 2
- overextension: 5
- valuation_warning: 1
- insider_selling: 1
- high_turnover: 1

## 10–11. Eight focus stocks

### 汉森制药 (002412.SZ)
- Scores: candidate=1.0894986447837294, leader=None, profit=None, event=None, news=0.5559558359089848, ml=None, stage=EXTREME, chase=3.0418356478525768, boards=4
- Council: **WATCH** / action **WAIT_FOR_CONFIRMATION** / risk ['limit_up']
- Conflict: insufficient_signals (0.0)
- Forward: {'1': -0.0018, '3': None, '5': None, '10': None, '20': None}, maxDD=0.0
- Path: council_not_buy:WATCH → trading_action:WAIT_FOR_CONFIRMATION → risk:['limit_up']

### 哈森股份 (603958.SH)
- Scores: candidate=1.0406625379139856, leader=None, profit=None, event=None, news=0.6499999999999999, ml=None, stage=EXTREME, chase=3.072790966226686, boards=3
- Council: **WATCH** / action **WAIT_FOR_CONFIRMATION** / risk ['limit_up']
- Conflict: insufficient_signals (0.0)
- Forward: {}, maxDD=None
- Path: council_not_buy:WATCH → trading_action:WAIT_FOR_CONFIRMATION → risk:['limit_up']

### 风范股份 (601700.SH)
- Scores: candidate=0.8693665130935764, leader=None, profit=None, event=None, news=0.65, ml=None, stage=EXTREME, chase=1.9156995327834745, boards=1
- Council: **WATCH** / action **WAIT_FOR_CONFIRMATION** / risk ['limit_up']
- Conflict: insufficient_signals (0.0)
- Forward: {'1': 0.0337, '3': None, '5': None, '10': None, '20': None}, maxDD=0.0
- Path: council_not_buy:WATCH → trading_action:WAIT_FOR_CONFIRMATION → risk:['limit_up']

### 天洋新材 (603330.SH)
- Scores: candidate=0.8613414343839321, leader=None, profit=None, event=None, news=0.16100741379596306, ml=None, stage=EXTREME, chase=2.1718722436635463, boards=2
- Council: **WATCH** / action **WAIT_FOR_CONFIRMATION** / risk ['limit_up']
- Conflict: insufficient_signals (0.0)
- Forward: {'1': -0.0264, '3': None, '5': None, '10': None, '20': None}, maxDD=0.0
- Path: council_not_buy:WATCH → trading_action:WAIT_FOR_CONFIRMATION → risk:['limit_up']

### 白银有色 (601212.SH)
- Scores: candidate=0.7335101070439348, leader=None, profit=None, event=None, news=0.39999999999999997, ml=None, stage=EXTREME, chase=1.767991342699777, boards=2
- Council: **WATCH** / action **WAIT_FOR_CONFIRMATION** / risk ['limit_up']
- Conflict: insufficient_signals (0.0)
- Forward: {'1': 0.0537, '3': None, '5': None, '10': None, '20': None}, maxDD=0.0
- Path: council_not_buy:WATCH → trading_action:WAIT_FOR_CONFIRMATION → risk:['limit_up']

### 科森科技 (603626.SH)
- Scores: candidate=0.7228535958060962, leader=None, profit=None, event=None, news=0.27674919621997934, ml=None, stage=EXTREME, chase=1.7882313291146075, boards=0
- Council: **AVOID** / action **NO_ACTION** / risk []
- Conflict: insufficient_signals (0.0)
- Forward: {'1': -0.0354, '3': None, '5': None, '10': None, '20': None}, maxDD=0.0
- Path: council_not_buy:AVOID → trading_action:NO_ACTION

### 盈新发展 (000620.SZ)
- Scores: candidate=0.6858996000976377, leader=None, profit=None, event=None, news=0.4408279903590744, ml=None, stage=EXTREME, chase=1.4062994286690222, boards=1
- Council: **WATCH** / action **WAIT_FOR_CONFIRMATION** / risk ['limit_up']
- Conflict: insufficient_signals (0.0)
- Forward: {'1': -0.0202, '3': None, '5': None, '10': None, '20': None}, maxDD=0.0
- Path: council_not_buy:WATCH → trading_action:WAIT_FOR_CONFIRMATION → risk:['limit_up']

### 赤天化 (600227.SH)
- Scores: candidate=0.6803038566147009, leader=None, profit=None, event=None, news=0.1989941320149387, ml=None, stage=EXTREME, chase=1.0175467915176786, boards=0
- Council: **WATCH** / action **NO_ACTION** / risk []
- Conflict: insufficient_signals (0.0)
- Forward: {'1': -0.0456, '3': None, '5': None, '10': None, '20': None}, maxDD=0.0
- Path: council_not_buy:WATCH → trading_action:NO_ACTION

## 12. Threshold audit (pass/fail counts)

- min_candidate_score: pass=20, fail=40
- min_leader_score: pass=0, fail=60
- min_ml_prediction: pass=0, fail=60
- min_profit_score: pass=0, fail=60
- min_event_score: pass=0, fail=60
- min_news_score: pass=0, fail=60
- research_gate_composite: pass=3, fail=57
- gate_reject_WEAK_SIGNALS: pass=0, fail=17
- gate_reject_LOW_CANDIDATE_SCORE: pass=0, fail=40

## 13. Conclusions

1. **Why almost no BUY?** Compound gate: Council never emits `SMALL_POSITION`; latest cycle has 0 BUY ratings; even WATCH names hit `limit_up` risk block.
2. **Too conservative or bad candidates?** Candidates are high-momentum limit-up/event names (quant-strong by design); conservatism is in Council+Action+Risk, not candidate scarcity.
3. **SQ+WN worse?** See quadrant table — weak-news strong-quant bucket aligns with chase/extreme stage.
4. **News role?** Currently weak positive signal; conflict flag `news_weak_quant_strong` should be risk gate, not rank booster.
5. **Late-stage chasing?** Yes — high board count, limit-up, ma_gap_20 elevated on focus names.
6. **Stage explains failures?** EXTREME/DISTRIBUTION dominates focus list.
7. **Stronger quant → more danger?** Driven by event/profit scores on already-extended prices, not alpha.
8. **Add chase_score?** Research supports veto/penalty at EXTREME; not yet in production.
9. **Negative evidence?** Chairman already cites risks; should become structured veto candidates.
10. **AI filtering?** Filters both bad chase names (AVOID) and potential winners; net effect inconclusive with 1-day sample.

## 14. Suggested changes (post-attribution only)

| Change | Expected improvement |
|---|---|
| Split **Research Rating** vs **Trade Timing**: allow `BUY` research + `WAIT` until non-limit day | Unblocks limit_up risk without lowering quality bar |
| Promote `news_weak_quant_strong` to **hard risk gate** before council budget | Reduces LLM spend on chase bucket; flags SQ+WN earlier |
| Stage-aware chase veto at EXTREME (research rule → production) | Cuts limit-down tail on 3–4 board names |
| Negative evidence schema (regulatory, turnover, insider) as penalty not just text | Stops weak-news momentum traps |
| Fix conflict detector to flag SQ+WN on platform reports (not `aligned`) | Aligns UI bucket with canonical downgrade |
| T+1 open fill path when signal day limit-up | Makes BUY_RATE measurable; respects no same-bar fill |