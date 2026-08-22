# V5.2 Alpha Attribution — Canonical Metrics

**Status:** Phase 4 complete (2026-08-22)

---

## 1. Canonical `ai_incremental_alpha`

**V5.2 rule:** `research_outcomes.ai_incremental_alpha` **is** the same-universe Top-K ablation result.

| Field | Meaning |
|-------|---------|
| `method` | `same_universe_topk_ablation` |
| `canonical` | `true` |
| `ai_incremental_alpha` | mean(AI Top-K) − mean(Baseline Top-K) |
| `baseline_topk` | Rank by `candidate_score` / factor |
| `ai_topk` | Rank by council rating + confidence |

Legacy cohort compare moved to **`ai_incremental_alpha_legacy`** (quant_only vs council_reviewed — different universes, not causal).

---

## 2. Role Ablation (Experimental)

**Module:** `src/ashare/research/role_ablation.py`  
**API:** `GET /api/research/role-ablation`

Offline replay: drop one council role, recompute synthetic chair score, compare Top-K mean return vs full council.

**Not** re-run LLM. Label: `experimental: true`.

---

## 3. Model × Token Benchmark

**Module:** `src/ashare/research/model_benchmark.py`  
**API:** `GET /api/research/model-benchmark`

Rolls up cycle `by_model` / `by_role` from cost tracker. Optional `alpha_per_100k_tokens` when canonical alpha available.

---

## 4. Dual Benchmark Alpha (Phase 1)

Per outcome horizon:

- `market_alpha` = return − CSI300 (or fallback)
- `selection_alpha` = return − equal-weight universe
- `benchmark_snapshot` = requested/actual/fallback truth

---

## 5. UI

- **Research → News:** lifecycle badge + `price_in_score`
- **Research → Alpha:** canonical AI Δ, role ablation table, model token rollup
- **Agent → Alpha tab:** uses `/api/research/alpha-dashboard` canonical fields

---

## 6. Tests

`tests/test_v5_2_alpha_ablation.py` — canonical unification, role ablation, model benchmark.
