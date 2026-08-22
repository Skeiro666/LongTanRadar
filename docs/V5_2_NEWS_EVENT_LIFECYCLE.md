# V5.2 News Event Lifecycle

**Status:** Implemented 2026-08-22  
**Module:** `src/ashare/news/event_lifecycle.py`

---

## State Machine

```
NEW → CONFIRMED → DEVELOPING → PRICED_IN → MONETIZING → RESOLVED
                              ↘ INVALIDATED / REJECTED
```

| Status | Trigger (research-only) |
|--------|-------------------------|
| `NEW` | Fresh discovery |
| `CONFIRMED` | confidence ≥ 0.55 + official entity link |
| `DEVELOPING` | 1–5 trading days since event, not priced-in |
| `PRICED_IN` | price_in_risk HIGH/MEDIUM or price_in_score ≥ 0.45 |
| `MONETIZING` | ret_since_event ≥ 5% on bullish news |
| `RESOLVED` | T+20 outcome or horizon elapsed |
| `INVALIDATED` | explicit invalidate flag |
| `REJECTED` | funnel reject |

**Never** maps to BUY/SELL automatically.

---

## Fields on NewsCandidate

- `lifecycle_status`, `lifecycle_reason`  
- `price_in_score` (0–1)  
- `price_in_risk` (HIGH/MEDIUM/LOW/UNKNOWN)  
- `investment_hypothesis.expected_excess_return` (available=false if unknown)

---

## Price-In

Separate **news direction** from **trading impact**:

- Bullish news + already +30% move → `PRICED_IN`, not auto PASS  
- `price_in_score` feeds Council context as warning feature only

---

## UI

Research → News tab: lifecycle badge + price-in score

---

## Tests

`tests/test_v5_2_event_lifecycle.py`

---

## Not in Scope (by design)

- No new news providers  
- No LLM-based lifecycle transitions
