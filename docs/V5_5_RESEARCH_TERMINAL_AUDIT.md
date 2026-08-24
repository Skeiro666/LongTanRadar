# V5.5 Research Terminal Audit (baseline `ad86639`)

## Already implemented (V5.4.2)

| Module | Role | Data source |
|--------|------|-------------|
| `news_alpha.py` | Four alpha lanes + A/B/C/D | `research_outcomes.jsonl` at read time |
| `news_calibration.py` | Score/importance/novelty buckets + quadrants | Outcomes, recomputed |
| `news_ablation.py` | Experiment arms | Outcomes, offline |
| `token_attribution.py` | Local vs cloud from `usage.jsonl` | Real ledger |
| `cloud_escalation.py` | Selective deep context | Per candidate at council run |
| `compact.py` | Structured news for Council | `collect_stock` / engine |
| `merge_intel.py` | Intel → ExtractedEvent | Local Ollama |
| Snapshots | Full point-in-time | `data/research_snapshots/{id}.json` |

## Real vs display-only

| Metric | Real calculation | Notes |
|--------|------------------|-------|
| T+N returns / alpha | Yes | `tracking.py` primary_horizons |
| News alpha lanes | Yes | Filter on outcomes; min sample gate |
| Calibration buckets | Yes when n≥min | Else `INSUFFICIENT_SAMPLE` |
| Signal contribution bars | Relative weights | **Not causal attribution** |
| Historical cohort | Structured match | **Not AI similarity** |
| Token saved % | Partial | Cache hits in usage.jsonl; baseline estimated |
| Cloud escalation funnel | Partial | Escalation logged on report; funnel needs history |

## Sample insufficiency

Default `minimum_sample_size=30` in `research.yaml`. Alpha Lab must not show green returns when `status=INSUFFICIENT_SAMPLE`.

## Look-ahead risks

- News filtered by `filter_asof(published_at <= signal_time)` at fetch
- Outcomes use signal-time prices; horizons forward-only
- Snapshots freeze news_package at research time — detail API must prefer snapshot over live recompute

## Frontend gaps (pre-V5.5)

- Research page: list-heavy, no signal-first cards, no matrix, council always expanded
- Alpha Lab: JSON dumps for calibration/ablation
- No research detail route; snapshots API unused
- Notifications: no per-row outcomes or snapshot link
- Overview: equity-first, not research-first

## V5.5 additions

- `GET /api/research/terminal` — dashboard + candidate cards + matrix
- `GET /api/research/detail/{research_id}/{symbol}` — full explainability payload
- `GET /api/notifications/history` — notifications + outcomes
- `GET /api/token-dashboard` — local/cloud/escalation funnel
- Alpha Lab: tables/charts, experiment deltas, insufficient-sample styling
- Research / Overview / Notifications UX refactor (backend-driven)
