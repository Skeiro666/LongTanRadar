# V5.2 Implementation Summary

**Project:** LongTan Radar  
**Completed:** 2026-08-22  
**Baseline:** V5 commit `2abeee6`

---

## Phases Delivered

| Phase | Scope | Doc |
|-------|-------|-----|
| 0 | Read-only audit | `docs/V5_2_AUDIT.md` |
| 1 | Dual benchmark, roundtable sampling, paper execution IDs, frontend alpha | `docs/V5_2_BENCHMARK.md` |
| 2 | Event lifecycle, price_in_score, expected_excess_return, as_of fix | `docs/V5_2_EVENT_LIFECYCLE.md` |
| 3 | Role-specific cache hash, chairman slim context | `docs/V5_2_COST_OPTIMIZATION.md` |
| 4 | Canonical ai_incremental_alpha, role ablation, model benchmark | `docs/V5_2_ALPHA_ATTRIBUTION.md` |
| 5 | Dashboard UI (Research News/Alpha tabs) | this file |

---

## Key API Additions

- `GET /api/research/role-ablation`
- `GET /api/research/model-benchmark`
- `GET /api/research/alpha-dashboard` — now exposes canonical + legacy alpha

---

## Config (`config/research.yaml`)

```yaml
roundtable_mode: sampled  # in default.yaml ai section
role_ablation:
  enabled: true
  top_k: 5
model_benchmark:
  enabled: true
```

---

## Test Suite (V5.2)

```bash
pytest tests/test_v5_2_benchmark.py tests/test_v5_2_event_lifecycle.py \
       tests/test_v5_2_cost_optimization.py tests/test_v5_2_alpha_ablation.py -q
```

---

## Not Changed (by design)

- No live broker routing
- Optimizer `auto_apply: false` unchanged
- Legacy roundtable retained for AB (`sampled` default reduces calls ~15–25%)

---

## Remaining Optional Work

- Shadow chairman quality A/B after context compression
- Production cache hit rate metrics on snapshot
- Fix pre-existing `test_ml_train_window.py` failures
