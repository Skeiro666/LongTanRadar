# V5.2 ML Weight Walk-Forward Experiment

**Status:** Module exists; formal experiment doc (2026-08-22)

---

## Rule

**Do not** manually pick ML weight for production. Use walk-forward experiment with train/validation/test or rolling windows.

Module: `src/ashare/ml/weight_experiment.py`  
API: `POST /api/ml/weight-experiment`  
Tests: `tests/test_ml_weight_experiment.py`

---

## Grid (recommended)

| ML weight | Horizons to score |
|-----------|-------------------|
| 0.00 | T+1, T+5, T+10, T+20 |
| 0.05 | |
| 0.10 | |
| 0.15 | |
| 0.20 | |

Metrics per cell:

- `return`, `market_alpha`, `selection_alpha`  
- `hit_rate`, `max_drawdown`, `turnover`  
- `sample_count`, `cost` (if research path)

---

## Safety

- Results persist to `data/ml/weight_experiments.jsonl`  
- **Never auto-apply** best weight to `config/research.yaml`  
- Optimizer / agent `auto_apply: false` by default  
- Approve via explicit experiment gate only

---

## Benchmark Alignment Note

ML training target in `config/models.yaml` may use `equal_weight_universe`. Research attribution uses CSI300 + EW dual benchmark. When comparing ML experiment outcomes to research attribution, **use the same benchmark pack** (`resolve_dual_benchmark_pack`).

---

## Insufficient Sample

If `sample_count < minimum` → `insufficient_sample: true`, no weight recommendation.

---

## Tests

```bash
pytest tests/test_ml_weight_experiment.py -q
```
