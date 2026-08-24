# AUTONOMOUS V6 AUDIT — Exit Engine

**Date:** 2026-08-24  
**Baseline commit:** `66b4872` (Chinese UI) / V5.5 Research Terminal  
**Mode:** Autonomous — code first, no fabricated metrics.

---

## 1. Current Architecture

```
行情 → 股票池 → 因子 → 新闻 → Candidate → ML → Council → Risk
  → Paper BUY → Outcome → Alpha Attribution → Research Terminal / Alpha Lab
```

- **BUY path:** Research picks → `execute_picks` → PaperBroker BUY (T+1 available)
- **SELL path (production):** essentially **missing** — agent never auto-sells
- **SELL path (backtest):** rebalance via `intents_from_weights` only
- **Notifications:** BUY / STRONG_BUY / RISK_EXIT / RATING_EXIT (alerts, not fills)

## 2. Implemented

- News Intelligence, Candidate union, Council, RiskFilter (open)
- Paper broker with T+1, fees, stamp tax, limit/halt
- Research Terminal / Alpha Lab / Token / Notification History
- MLRankingEngine + classic LightGBM (entry ranking)
- Outcome tracking for research / notification (entry-forward)

## 3. Not Implemented (pre-V6)

- Exit Engine / exit_score / REDUCE|EXIT signals
- Position lifecycle fields (entry_date, peak, drawdown, thesis)
- Exit backtest vs fixed hold / stop
- Exit Alpha / Early-Good-Late classification
- Thesis decay
- ALPHA_EXIT notification
- Position Exit UI / charts
- Exit ML model

## 4–10. Data Flows

| Flow | Status |
|------|--------|
| BUY | Research → picks → execute_picks → Position |
| SELL | Backtest rebalance only; paper SELL API exists but unused by agent |
| Outcome | Signal-day forward returns; no exit_time/exit_price chain |
| Alpha | News/source alpha; no Exit Alpha |
| Token | Local/Cloud attribution for news/council |
| Frontend | Overview positions = cost/shares only |

## 11. Top Technical Debt

1. No production exit path
2. Thin `Position` model
3. Notification `_paper_positions` uses `quantity` not `shares` (bug)
4. RISK/RATING_EXIT do not execute
5. Outcomes lack exit attribution
6. Agent buy-only cycle
7. Rebalance-only backtest exits
8. No exit config
9. Overview UI incomplete for hold/exit
10. Factor stubs (sector RS) unavailable

## 12. Top 10 Optimizations (this cycle)

1. Exit Feature Engine (reuse factors)
2. Heuristic exit_score + thresholds
3. Forward-return labels (as_of safe)
4. Exit backtest (No / Fixed / Engine)
5. Exit quality EARLY/GOOD/LATE
6. Exit Alpha + giveback
7. Thesis decay
8. ALPHA_EXIT notify + snapshot
9. Position Exit UI + chart
10. Tests + asof leakage checks

## Decision

- Package: `src/ashare/portfolio/exit/`
- Config: `config/exit.yaml`
- Signals only — no live broker; paper execute optional via existing APIs
- BUY system untouched
- ML Exit only if sample ≥ minimum; else HEURISTIC
