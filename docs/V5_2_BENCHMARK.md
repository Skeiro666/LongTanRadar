# V5.2 Benchmark — Market vs Selection Alpha

**Phase 1 implemented:** dual benchmark resolution, honest fallback, snapshot persistence.

## Definitions

| Term | Formula | Benchmark |
|------|---------|-----------|
| **Total Return** | stock forward return | — |
| **Market Alpha** | stock_return − CSI300_return | 000300 index |
| **Selection Alpha** | stock_return − universe_EW_return | Equal-weight research panel |

Do **not** label equal-weight universe as CSI300.

## Snapshot schema (every research run)

```json
{
  "requested": "csi300",
  "actual": "csi300",
  "index": "000300",
  "fallback": false,
  "fallback_reason": null,
  "as_of": "2026-08-22",
  "market_benchmark": { "method": "csi300", "returns": { "5": 0.04 } },
  "universe_benchmark": { "method": "equal_weight_universe", "returns": { "5": 0.07 } }
}
```

On CSI300 fetch failure:

```json
{
  "requested": "csi300",
  "actual": "equal_weight_universe",
  "fallback": true,
  "fallback_reason": "csi300_unavailable"
}
```

## Code

- `resolve_dual_benchmark_pack()` — `src/ashare/research/benchmark.py`
- Outcome horizons — `market_alpha`, `selection_alpha` in `tracking.py`
- Payload — `research_outcomes.benchmark_snapshot`

## Roundtable schedule (Token savings)

| Mode | Behavior |
|------|----------|
| `disabled` | No legacy roundtable LLM |
| `sampled` | Every N runs (default 10) |
| `scheduled` | Max M per day (default 1) |
| `benchmark` | Every run (AB only) |

Default config: `roundtable_mode: sampled`, `roundtable_sample_every: 10`.

## Tests

`tests/test_v5_2_benchmark.py`
