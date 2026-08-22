# V5.2 Model Routing & Role × Model Benchmark

**Status:** Experimental rollup (2026-08-22)

---

## Current Implementation

**Not** online Role×Model A/B swapping in production.

**Implemented:**

- `src/ashare/research/model_benchmark.py` — cycle token/cost rollup by model & role  
- `/api/research/model-benchmark`  
- Multi-model config in `config/default.yaml` → `ai.committee.roles`

---

## Production Model Map (default)

| Role alias | Model (example) |
|------------|-----------------|
| dragon / quant / fundamental | Qwen/Qwen3.5-122B-A10B |
| event / valuation | DeepSeek-V4-Flash |
| risk / bear | Kimi-K2.6 |
| chair | DeepSeek-V4-Flash |

---

## Experimental Benchmark Output

```json
{
  "models": [
    { "model": "...", "tokens": 60000, "cost_usd": 0.03, "alpha_per_100k_tokens": 0.02 }
  ],
  "roles": [
    { "role": "quant", "tokens": 30000, "cost_usd": 0.015 }
  ],
  "experimental": true
}
```

**Interpretation:** Descriptive cost routing only — not proof of model quality.

---

## Future: Role × Model Experiment

Spec requires offline/scheduled runs comparing Event/Bear/Chairman across Qwen/DeepSeek/Kimi with:

- hit_rate, market_alpha, selection_alpha  
- input/output tokens, cost, latency  

Gate: `experimental=true`, minimum sample_count, no auto-promote to production.

---

## Tests

`tests/test_v5_2_alpha_ablation.py` — `test_model_benchmark_from_cycle`
