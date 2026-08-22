# V5.2 Phase 3 — Cost Optimization (Cache + Chairman)

**Status:** Implemented 2026-08-22

---

## 1. Role-Specific Context Hash

`project_context_for_hash(role_id, context)` in `cache.py` strips each role's cache key to role-relevant fields only.

**Problem fixed:** News timeline / evidence churn no longer invalidates quant cache when quant inputs unchanged.

`compute_context_hash()` always hashes the projected subset.

---

## 2. Chairman Slim Context

`build_chairman_context()` (compression enabled) now sends:

| Field | Content |
|-------|---------|
| `role_reports` | Slim analyst opinions (score, stance, points, risks) |
| `evidence_ids` | Registry IDs only |
| `candidate_sources` | Discovery tags |
| `price_in_risk` | Warning flag |
| `rules` | Council constraints |
| `debate` | Structured rebuttals |
| `missing_roles` | Failed/unavailable roles |

**Removed from chairman LLM input:** full `research_intelligence`, `quant_summary`, duplicate hypotheses grid.

Chairman cache key uses `role_reports + evidence_ids + debate` only.

---

## 3. Tests

- `tests/test_v5_2_cost_optimization.py`
- Updated `tests/test_role_context.py`

---

## 4. Expected Token Impact (est.)

- Chairman input: **−20–40%** tokens vs V5 full intel blob
- Cache hit rate: **+10–25%** on repeat runs when news changes but quant context stable
