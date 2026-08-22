# V4 Optimization Benchmark

Baseline audit: `docs/V4_OPTIMIZATION_AUDIT.md` (Phase 0, pre-V4).

## Baseline (Phase 0)

| Metric | Value |
|--------|-------|
| LLM calls / full research run | ~76 (4 roundtable + 12×6 council) |
| LLM calls / agent cycle | ~77 (+1 optimizer) |
| Token tracking | None |
| Research Gate | None |
| Dynamic Council | Fixed 5 roles always |
| Context compression | Full intel to every role |
| Research cache | None (except ai_select date cache) |
| Benchmark excess in attribution | Always `null` |

## V4 Implemented (Phases 1–9)

| Phase | Feature | Config key |
|-------|---------|------------|
| 1 | `AICostTracker` + `/api/ai/cost` | `ai.cost_tracking` |
| 2 | `build_role_context()` per role | `research.context_compression` |
| 3 | Event clusters + compact headlines | `news/package.py` + `news/cluster.py` |
| 4 | `ResearchCache` disk cache | `research.research_cache` |
| 5 | Dynamic Council role selection | `research.dynamic_council` |
| 6 | Research Gate before council | `research.research_gate` |
| 7 | Incremental reuse prior snapshot | `research.incremental_research` |
| 8 | Equal-weight benchmark → excess_return | auto in `run_research()` |
| 9 | `ai_incremental_alpha` in attribution | `ReviewEngine.compute_ai_incremental_alpha` |
| 10 | Frontend cost panel | Agent page → `/api/ai/cost` |

## Expected Ranges (warm cache, default config)

| Metric | Baseline | V4 target |
|--------|----------|-----------|
| Council symbols / run | 12 | 3–8 (gate) |
| LLM calls / symbol (council) | 6 | 2–4 (dynamic roles) |
| Input tokens / council role | ~3–4.5k | ~2–3k (compression) |
| Repeat symbol same day | Full re-call | Cache hit → 0 LLM |
| `excess_return` in outcomes | null | populated when panel ≥2 symbols |

## How to Measure

1. Run one research cycle: `POST /api/research/run`
2. Check cost: `GET /api/ai/cost` → `cycle.total_tokens`, `estimated_usd`, `cache_saved_tokens`
3. Check gate: report JSON `candidate_union.gate` → `n_passed`, `n_rejected`
4. Check attribution: `research_outcomes.ai_incremental_alpha` + `benchmark_wired: true`
5. Compare log file: `data/ai/usage.jsonl`

## Validation Checklist

- [ ] `usage.jsonl` grows only on cache miss
- [ ] Valuation role never calls LLM when `value_available=false`
- [ ] GATE_SKIP reports have no council LLM rows in usage log
- [ ] Second run same day: `cache_saved_tokens` > 0
- [ ] `research_outcomes.attribution.benchmark_wired` is true when panel loaded
- [ ] Agent page shows cost panel without errors

## Non-Goals (still manual / future)

- Live broker routing
- Cross-run OOS proof of AI alpha (needs walk-forward harness)
- Merging roundtable + platform council into single stack (config flag TBD)
