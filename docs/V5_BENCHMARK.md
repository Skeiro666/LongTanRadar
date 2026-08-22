# V5 Benchmark — Alpha & Cost Loop

Compare against V4 baseline (`docs/V4_BENCHMARK.md`) and Phase 0 audit (`docs/V5_PHASE0_AUDIT.md`).

## Summary Table

| Metric | V4 Baseline | V5 Target | V5 Implemented |
|--------|-------------|-----------|----------------|
| LLM calls / research (cold) | ~65–77 | 15–30 | Gate + Dynamic + Cache + Budget (measure per run) |
| Roundtable controls trading | Yes (fallback) | No | **No** — benchmark only |
| Canonical Decision | No | Yes | **Yes** |
| ML before Top-N | No | Yes | **Yes** |
| Token tracking | Yes | Yes | **Yes** + `research_session_id` |
| Cache hit rate | Partial | High on repeat | **Yes** — per-role context hash |
| Gate | Binary | DEEP/LIGHT/NO | **Yes** |
| AI Incremental Alpha | Cohort compare | Top-K ablation | **Yes** (`ai_topk_ablation`) |
| Optimizer direct prod | Yes | No | **No** — `auto_apply: false` |
| Alpha Dashboard UI | Cost only | Cost + Alpha | **Yes** |

## How to Measure

```bash
# 1. Run research
curl -X POST http://localhost:8000/api/research/run

# 2. Cost
curl http://localhost:8000/api/ai/cost

# 3. Alpha dashboard
curl http://localhost:8000/api/research/alpha-dashboard?horizon=5

# 4. Usage log
type data\ai\usage.jsonl
```

## Expected Token Reduction (warm cache, typical)

| Mechanism | Est. savings |
|-----------|--------------|
| Roundtable not driving trades (still runs for benchmark) | ~5–8% calls |
| Research Gate + tiers | ~25–35% |
| Dynamic Council profiles | ~20–30% role calls |
| Research Cache (2nd run) | ~30–50% |
| Incremental NO_CHANGE | ~15–25% daily |
| LLM budget cap (30/cycle) | Hard ceiling |

**Cumulative realistic:** 55–70% token reduction vs pre-V4.

## Alpha Metrics

| Metric | Source | Notes |
|--------|--------|-------|
| Discovery Alpha (quant/news/…) | `discovery_attribution` | n&lt;3 → `insufficient_sample` |
| AI Incremental Alpha | `ai_topk_ablation.ai_incremental_alpha` | Same universe Top-K |
| α per 100k tokens | `alpha-dashboard.cost.alpha_per_100k_tokens` | Requires both α and tokens |
| Excess return | `outcomes.horizons.*.excess_return` | CSI300 when available; else EW fallback |
| Paper fill entry | `outcomes.execution` | Links PG `fills` → outcome slippage |

## Benchmark (`config/research.yaml`)

```yaml
tracking:
  benchmark: csi300                    # primary: 000300 index
  benchmark_fallback: equal_weight_universe
  execution_tracking: true             # attach paper fills to outcomes
```

When CSI300 fetch fails, system falls back to equal-weight universe proxy and sets `fallback_from: csi300_unavailable`.

## Validation Checklist

- [ ] `decision_consistency.ok == true` in latest research JSON
- [ ] Paper buys match `canonical_decisions` approved symbols
- [ ] `usage.jsonl` shows `usage_source: actual` when provider returns usage
- [ ] Gate rejects appear as `GATE_SKIP` without council LLM rows
- [ ] `optimizer.auto_apply: false` — no `agent_overrides.yaml` without approve
- [ ] Research page Alpha Dashboard renders after one run
- [ ] `ai_topk_ablation.insufficient_sample` when &lt;2 outcomes

## Honest Limits

- Benchmark is **equal-weight universe**, not CSI300/中证500
- AI Incremental Alpha needs **realized forward returns** — early runs show `pending`
- Sample size on ¥3000 paper account is **small** — do not over-interpret α
