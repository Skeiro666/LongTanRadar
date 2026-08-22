# V5.2 Phase 2 — Event Lifecycle & Price-In Features

**Status:** Implemented 2026-08-22  
**Depends on:** V5.2 Phase 1 benchmark / paper outcome

---

## 1. Event Lifecycle State Machine

Research-only semantics — **never** maps to BUY/SELL.

| Status | Meaning | Typical trigger |
|--------|---------|-----------------|
| `NEW` | Fresh discovery, low price-in | `price_in_risk` LOW/UNKNOWN |
| `PRICED_IN` | Move likely reflects news | `price_in_risk` HIGH/MEDIUM or elevated `price_in_score` |
| `RESOLVED` | Horizon elapsed or outcome measured | T+20 outcome or ≥20 trading days since event |
| `REJECTED` | Funnel/discovery reject | `status=REJECTED` on candidate |

**Module:** `src/ashare/news/event_lifecycle.py`  
**Applied in:** `annotate_news_candidate_price()` after price reaction compute.

Fields on `NewsCandidate`:
- `lifecycle_status`
- `lifecycle_reason`
- `price_in_score` (0–1, higher = more priced in)

---

## 2. expected_excess_return

On `investment_hypothesis` inside each `ResearchHypothesis`:

```json
{
  "available": false,
  "value": null,
  "horizon": "ORDER",
  "confidence": 0.0,
  "note": "无一致预期/模型预测，未伪造 expected_excess_return"
}
```

When `ExtractedEvent.expectation_available` and `expectation_gap` exist, `available=true` and `value` is set from gap. **Never fabricated.**

---

## 3. as_of Leak Fix

`CandidateEngine.build_research_universe(..., as_of=)` now passes `as_of` to:
- `annotate_news_candidate_price(..., as_of=)`
- `NewsIntelligenceEngine.collect_stock(..., as_of=)`

`run_research()` wires `as_of_dt.isoformat()` into the candidate funnel.

---

## 4. Tests

`tests/test_v5_2_event_lifecycle.py` — lifecycle transitions, price_in_score, expected_excess_return, collect_stock as_of propagation.

---

## 5. Not in Phase 2

- Role-specific context hash (Phase 3)
- Chairman compression (Phase 3)
- AI incremental alpha unification (Phase 4)
- Dashboard lifecycle UI (Phase 5)
