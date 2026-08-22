# V5.2 Paper ↔ Outcome Truth Model

**Status:** Implemented 2026-08-22

---

## Single Truth Rule

| Metric | Source | Field |
|--------|--------|-------|
| Account equity / day PnL | Paper broker | `/api/pnl` |
| Per-symbol alpha / attribution | Research outcomes | `primary_horizons` |

**Priority for per-symbol returns:**

1. `execution.horizons_from_fill` (paper fill entry)  
2. `horizons` (signal-day close entry)

Module: `src/ashare/research/outcome_truth.py`

---

## Cross-link

`/api/pnl` includes `research_link` pointing to latest `research_outcomes`:

- `portfolio_attribution` — aggregated primary-horizon stats  
- `benchmark_snapshot`  
- `ai_incremental_alpha`  
- `outcome_truth` metadata  

Account PnL and research alpha are **linked, not merged** — avoids fabricating per-symbol returns from portfolio equity.

---

## Outcome Fields (per symbol)

Each outcome after attribution:

```json
{
  "primary_source": "paper_fill | signal_close",
  "primary_horizons": { "5": { "actual_return", "market_alpha", "selection_alpha" } },
  "execution": { "decision_id", "fill_time", "fill_price", "horizons_from_fill" }
}
```

---

## Tests

`tests/test_v5_2_outcome_budget.py`
