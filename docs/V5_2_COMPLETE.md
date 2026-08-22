# V5.2 Implementation Summary

**Project:** LongTan Radar  
**Latest:** 2026-08-22 (outcome truth + LLM budget + docs completion)

---

## Phases Delivered

| Phase | Scope | Doc |
|-------|-------|-----|
| 0 | Read-only audit | `docs/V5_2_AUDIT.md` |
| 1 | Dual benchmark, roundtable sampling, paper execution IDs | `docs/V5_2_BENCHMARK.md`, `docs/V5_2_OUTCOME_TRUTH.md` |
| 2 | Event lifecycle, price_in_score, expected_excess_return, as_of fix | `docs/V5_2_NEWS_EVENT_LIFECYCLE.md` |
| 3 | Role-specific cache hash, chairman slim context | `docs/V5_2_COST_OPTIMIZATION.md` |
| 4 | Canonical ai_incremental_alpha, role ablation, model benchmark | `docs/V5_2_ALPHA_ATTRIBUTION.md` |
| 5 | Dashboard UI + documentation set | this file |

## Full Doc Index

- `V5_2_AUDIT.md` — Phase 0 audit (code baseline)
- `V5_2_BENCHMARK.md` — Market / Selection alpha
- `V5_2_OUTCOME_TRUTH.md` — Paper ↔ outcome primary horizons
- `V5_2_ALPHA_ATTRIBUTION.md` — AI incremental alpha
- `V5_2_NEWS_EVENT_LIFECYCLE.md` — Event states + price-in
- `V5_2_COST_OPTIMIZATION.md` — Cache + chairman
- `V5_2_TOKEN_COST.md` — Ledger + LLM budget
- `V5_2_MODEL_ROUTING.md` — Model × role rollup
- `V5_2_ML_WEIGHT_EXPERIMENT.md` — Walk-forward ML weight

---

## Key Modules (new in V5.2)

| Module | Purpose |
|--------|---------|
| `research/outcome_truth.py` | paper_fill > signal_close primary metrics |
| `research/llm_budget.py` | max calls/tokens/cost hard stop |
| `news/event_lifecycle.py` | NEW→…→RESOLVED state machine |
| `research/role_ablation.py` | experimental offline replay |
| `research/model_benchmark.py` | token/cost rollup by model |

---

## Test Suite

```bash
pytest tests/test_v5_2_*.py tests/test_ml_weight_experiment.py -q
```

---

## Remaining (optional V5.2+)

- Online Role×Model A/B (scheduled experiments)
- Single merged PnL table (account + attribution export)
- §36 before/after production benchmark table (requires live run)
- Shadow chairman quality A/B after compression

---

## Config Highlights

`config/research.yaml`:

```yaml
llm_budget:
  max_llm_calls: 30
  max_input_tokens: 800000
  max_output_tokens: 200000
  max_cost_usd: 5.0
roundtable_mode: sampled  # in default.yaml ai section
```

---

*Do not add roles/prompts/news sources/factors in V5.2 scope.*
