# V5 Alpha & Attribution

## Outcome Tracking

**Module:** `src/ashare/research/tracking.py`

Each platform report → forward returns at horizons `[1,3,5,10,20,60]`:

| Field | Meaning |
|-------|---------|
| `actual_return` | Stock return from research as_of entry |
| `benchmark_return` | Equal-weight universe proxy (if ≥2 symbols in panel) |
| `excess_return` | `actual - benchmark` when benchmark wired |
| `status: pending` | Not enough forward bars yet |

Persisted: `data/research_outcomes.json`

## Discovery Attribution

**Method:** Group outcomes by `candidate_sources` tags.

```json
"discovery_attribution": {
  "horizon": "5",
  "sources": {
    "quant": { "n": 12, "mean_return": 0.02, "insufficient_sample": false },
    "news": { "n": 2, "mean_return": null, "insufficient_sample": true }
  }
}
```

- Tags: `quant`, `news`, `event`, `profit`, `ml`
- **n &lt; 3** → mark `insufficient_sample: true` — do not claim edge

## AI Incremental Alpha (V5 — Top-K Ablation)

**Correct method (implemented):**

1. Same research run universe (all council reports, same as_of)
2. Exclude `GATE_SKIP`
3. **Baseline Top-K:** sort by `candidate_score` / `factor_score`
4. **AI Top-K:** sort by `research_rating` + chairman `confidence`
5. Compare mean excess (or actual) return at horizon H
6. `ai_incremental_alpha = mean(AI Top-K) - mean(Baseline Top-K)`

API field: `research_outcomes.ai_topk_ablation`

Legacy cohort compare (`ai_incremental_alpha_legacy`) retained for reference — **not** causal proof.

## Role Incremental Value

**Status:** experimental — not strict ablation yet.

Future: leave-one-role-out council reruns. Current: council `_meta.call_reasons` / `skip_reasons` for audit only.

## Cost Efficiency

```
alpha_per_100k_tokens = ai_incremental_alpha / (total_tokens / 100_000)
```

Only computed when both α and token count are valid. Shown on Agent + `/api/research/alpha-dashboard`.

## Benchmark Honesty

| Benchmark | Status |
|-----------|--------|
| Equal-weight universe | **Implemented** — `equal_weight_benchmark_returns()` |
| CSI300 / 中证500 | **Not wired** — would need index series in panel |
| Fake excess | **Forbidden** — `excess_return: null` when no benchmark |

## Paper Trading vs Research Outcomes

- Research outcomes track **research pool** forward returns
- Paper fills are **not yet linked** to outcome ledger
- Do not equate paper PnL with discovery α without explicit join

## Optimizer & Experiments

- Proposals: `data/optimizer_experiments.jsonl`
- Production apply: only via `approve_experiment()` or `optimizer.auto_apply: true`
- No walk-forward auto-approval in V5.1 — manual review required

## Reading the Dashboard

**Research page → Alpha · Cost Dashboard**

- LLM calls / tokens / USD for this research run
- AI Incremental α (Top-K) with Baseline vs AI columns
- Discovery Attribution per source
- Source bucket stats with excess when benchmark wired

**Agent page → AI Cost · Alpha Loop**

- Live cycle cost + efficiency metrics
- Latest research α snapshot (refreshed every 4s)
