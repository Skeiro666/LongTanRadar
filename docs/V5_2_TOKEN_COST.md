# V5.2 Token Cost & LLM Budget

**Status:** Implemented 2026-08-22

---

## Cost Ledger (existing V5)

Each LLM call records via `AICostTracker`:

| Field | Notes |
|-------|-------|
| `request_id` | Unique |
| `cycle_id` | Research run |
| `research_session_id` | Per symbol session |
| `symbol`, `role`, `call_site` | |
| `model`, `provider` | |
| `input_tokens`, `output_tokens`, `total_tokens` | |
| `usage_source` | `actual` \| `estimated` \| `cache` |
| `estimated_cost_usd` | From config rates |
| `cache_hit`, `cache_saved_tokens` | |
| `latency_ms`, `timestamp` | |

Log: `data/ai/usage.jsonl`

---

## LLM Budget (V5.2)

Config: `config/research.yaml` → `llm_budget`

```yaml
llm_budget:
  enabled: true
  max_llm_calls: 30
  max_input_tokens: 800000
  max_output_tokens: 200000
  max_cost_usd: 5.0
```

**0 = unlimited** for token/cost caps.

Module: `src/ashare/research/llm_budget.py`

Enforcement:

- `ResearchSessionEngine.run_pool()` — skip candidate when hard stop  
- `AICouncilEngine._call_role()` / `ChairmanEngine` — heuristic fallback when exceeded  

Snapshot on each run: `gate.llm_budget` + `ai_cost.budget`

---

## Token Optimization Order (spec)

1. Don't call (Gate / Dynamic / Incremental / Roundtable sampled)  
2. Cache (role-specific hash)  
3. Incremental NO_CHANGE  
4. Dynamic Council  
5. Context compression  
6. Evidence IDs  
7. Chairman slim context  
8. Model routing (experimental)

---

## Dashboard Fields

| Metric | API |
|--------|-----|
| LLM Calls / Tokens / Cost | `/api/ai/cost`, `research.ai_cost` |
| Cache hit rate | `ai_cost.budget.used.cache_hit_rate` |
| Cost / Research / BUY | `/api/research/alpha-dashboard` → `cost.efficiency` |

---

## Tests

`tests/test_v5_2_outcome_budget.py` — budget hard stop

---

## Before/After Target (§36)

Run fixed `as_of` twice (pre/post V5.2 config) and compare:

| Metric | Baseline (V5) | V5.2 Target |
|--------|---------------|-------------|
| LLM calls / cycle | ~30–50 | −50% |
| Total tokens | variable | −50% |
| Cache hit rate (repeat) | ~0% | 40–80% |
| Roundtable calls | every run | sampled |

*Quantitative table requires production run — not fabricated in docs.*
