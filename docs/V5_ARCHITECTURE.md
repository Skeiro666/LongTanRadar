# V5 Architecture — Alpha & Cost Loop

**Version:** V5 (Alpha & Cost Loop)  
**Baseline:** V4 audit + `docs/V5_PHASE0_AUDIT.md`

## Target Loop

```
Discovery → Ranking → Research Gate → Dynamic Council → Chairman
    → RiskFilter → Canonical Decision → Paper Trading
    → Outcome → Attribution → Cost → Experiment → next cycle
```

## Decision Chain (Phase 1)

| Layer | Module | Controls trading? |
|-------|--------|-------------------|
| Legacy Roundtable | `ai/roundtable.py` | **No** (`benchmark_only`) |
| Platform Council | `research/council.py` | **Yes** (via Chairman) |
| Canonical Decision | `research/canonical_decision.py` | **Single source of truth** |
| Paper Trading | `services/trading.py` | Reads `canonical_decisions` only |

Payload fields: `canonical_decisions`, `decision_chain`, `decision_consistency`.

## Candidate & ML (Phase 2)

```
build_leader_pool + NewsOpportunityEngine
  → CandidateEngine.build_research_universe()
       MLRankingEngine.predict_rows()  ← BEFORE union Top-N cut
       apply_ml_rank_scores()            ← winsorize + percentile
       compute_candidate_score()         ← ml weight default 0.10
  → Top 20 research pool → collect_stock (Top-N only)
  → Research Gate → Dynamic Council
```

ML weight experiment: `ml/weight_experiment.py` → `data/ml/weight_experiments.jsonl` (walk-forward, no auto-apply).

## Cost Ledger (Phase 3)

- `AICostTracker` / alias `AICostLedger` — `data/ai/usage.jsonl`
- Fields: `request_id`, `cycle_id`, `research_session_id`, `role`, `usage_source` (actual|estimated)
- API: `GET /api/ai/cost`, `GET /api/research/alpha-dashboard`

## Research Optimization (Phases 4–7)

| Phase | Module | Config |
|-------|--------|--------|
| Cache | `research/cache.py` | `research.research_cache` |
| Dynamic Council | `research/dynamic_council.py` | `research.dynamic_council` |
| Gate tiers | `research/gate.py` | `research.research_gate` |
| Incremental | `research/incremental.py` | `research.incremental_research` |

Gate tiers: `DEEP_RESEARCH` / `LIGHT_RESEARCH` / `NO_RESEARCH`  
Budget: `max_llm_calls: 30` per cycle.

## News (Phase 8)

```
Raw News → Dedup → Entity Mapping → Event Extraction
  → Event Cluster (symbol+type+direction)
  → Evidence Registry (E1001…)
  → Investment Hypothesis (FACT/INFERENCE/HYPOTHESIS)
  → NewsCandidate (discovery only, ≠ BUY)
```

## Outcome & Attribution (Phase 9)

- `TrackingEngine` — T+1/3/5/10/20/60 horizons
- Benchmark: **CSI300 (000300)** when index data available; fallback equal-weight universe (`research/benchmark.py`)
- **Paper execution link:** PG `fills` → `outcomes.execution` slippage + fill-based returns
- **AI Incremental Alpha (Top-K ablation):** same universe, Baseline Top-K by score vs AI Top-K by rating
- **Discovery Attribution:** per-source quant/news/event/profit/ml stats
- Optimizer: `optimizer_experiment.py` — proposals only unless `optimizer.auto_apply: true`

## Key APIs

| Endpoint | Purpose |
|----------|---------|
| `POST /api/research/run` | Full research cycle |
| `GET /api/research/alpha-dashboard` | Cost + Alpha combined |
| `GET /api/ai/cost` | Token/cost rollup |
| `GET /api/research/attribution` | Source + Top-K ablation |
| `GET /api/optimizer/experiments` | Optimizer proposals |
| `GET /api/ml/weight-experiments` | ML weight grid walk-forward history |
| `POST /api/ml/weight-experiment` | Run ML weight grid (no auto-apply) |

## Frontend

- **Research** page: Alpha · Cost Dashboard, Canonical Decision source
- **Agent** page: Cost + AI Incremental α + Discovery Alpha

## Non-Goals (unchanged)

- Live broker routing
- AI direct orders
- Deleting Roundtable / Quant / News engines
