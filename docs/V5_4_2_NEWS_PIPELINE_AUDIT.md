# V5.4.2 News Pipeline Audit (baseline `7d6a867`)

## Already implemented at baseline

| Item | Status | Location |
|------|--------|----------|
| Task A / Task B separation | Done | `llm_mapping.py`, `intelligence.py`, `enrich.py` |
| Task B on rule-matched high-value news | Done | `funnel.is_high_value_news`, `extract_for_news` |
| DIRECT / INFERRED discovery | Done | `schema.discovery_grade`, `opportunity.discover`, `candidate/__init__.py` |
| Evidence collect_stock | Done | `engine.collect_stock` |
| Programmatic news_intelligence_score | Done | `intel_score.py`, `config/news.yaml` |
| Local cache + token budget | Done | `intel_cache.py`, `intelligence.py` |
| Basic news_conflict | Partial | `conflict.py` (leader_score only) |
| Council headline compression | Partial | `intel_package._compact_news_*` (drops structured intel) |
| Coarse news alpha cohorts | Partial | `signal_attribution.news_discovery_cohort` |

## Gaps addressed in V5.4.2

1. **merge_intel** — LLM intel merged into `ExtractedEvent` (backward compatible fields)
2. **compact_news_package** — structured Council payload (no raw dump)
3. **cloud_escalation** — selective deep Cloud context
4. **compute_news_quant_conflict** — RS/momentum/volume + price signals
5. **news_alpha** — four alpha types + A/B/C/D buckets
6. **news_calibration** — score/importance/novelty buckets + quadrants
7. **news_ablation** — offline experiment arms
8. **token_attribution** — Local vs Cloud rollup
9. **Alpha Lab UI** — news panels + token stats

## Files changed in V5.4.2

See git diff from `7d6a867`. Key additions:

- `src/ashare/news/merge_intel.py`
- `src/ashare/news/compact.py`
- `src/ashare/research/news_alpha.py`
- `src/ashare/research/news_calibration.py`
- `src/ashare/research/news_ablation.py`
- `src/ashare/research/token_attribution.py`
- `src/ashare/research/cloud_escalation.py`
- Tests: `test_news_intelligence_integration.py`, `test_news_alpha.py`, etc.

## Unchanged (by design)

Broker, Paper Trading, RiskFilter, Chairman, Notification types, candidate weight structure.
