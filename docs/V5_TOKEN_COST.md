# V5 Token & Cost Ledger

## Infrastructure

| Component | Path |
|-----------|------|
| Ledger | `src/ashare/ai/cost_tracker.py` (`AICostLedger` alias) |
| Log | `data/ai/usage.jsonl` |
| Client hook | `src/ashare/ai/client.py` → `_record_usage()` |
| Config | `config/default.yaml` → `ai.cost_tracking` |

## Record Schema

Each LLM call writes:

```json
{
  "request_id": "…",
  "timestamp": "ISO8601",
  "cycle_id": "research_YYYYMMDD_HHMMSS",
  "research_session_id": "R20250822…",
  "symbol": "600000.SH",
  "role": "quant|chairman|optimizer|…",
  "call_site": "council.role|agent.optimize|…",
  "model": "…",
  "provider": "…",
  "input_tokens": 0,
  "output_tokens": 0,
  "total_tokens": 0,
  "latency_ms": 0.0,
  "cache_hit": false,
  "usage_source": "actual|estimated",
  "estimated_cost_usd": 0.0,
  "cache_saved_tokens": 0
}
```

- **`usage_source=actual`** when provider returns `usage` block
- **`usage_source=estimated`** when missing — uses `estimate_tokens()`
- **Cache saves** recorded via `record_cache_save()` — no LLM call, `provider=cache`

## API Rollups

### `GET /api/ai/cost`

| Field | Description |
|-------|-------------|
| `cycle_cost.n_calls` | LLM calls this cycle |
| `cycle_cost.input_tokens` / `output_tokens` | Token split |
| `cycle_cost.estimated_usd` | USD estimate from config rates |
| `cycle_cost.cache_saved_tokens` | Tokens avoided via cache |
| `cycle_cost.role_cost` / `symbol_cost` / `model_cost` | Breakdowns |
| `efficiency.tokens_per_candidate` | total / n_union |
| `efficiency.tokens_per_research` | total / n_council |
| `efficiency.tokens_per_buy` | total / n_buys |
| `efficiency.cost_per_buy` | USD / n_buys |

### `GET /api/research/alpha-dashboard`

Adds `alpha_per_100k_tokens` when Top-K incremental α and tokens both available.

## Token Optimization Stack (V5)

1. **Research Gate** — skip weak candidates before any LLM
2. **Dynamic Council** — 2–4 roles/symbol vs fixed 5
3. **Research Cache** — context hash per role (incl. `news_version`, `candidate_hash`)
4. **Incremental Research** — `NO_CHANGE` → reuse prior opinions
5. **Context compression** — `build_role_context()` slim payloads
6. **LLM budget** — `max_llm_calls: 30` hard cap per cycle
7. **Roundtable benchmark-only** — still ~4 calls but **not** on trading path

## Cost Rates

Configure in `config/default.yaml`:

```yaml
ai:
  cost_tracking:
    usd_per_1m:
      default_input_per_1m: 0.5
      default_output_per_1m: 1.5
      models:
        deepseek-chat:
          input_per_1m: …
          output_per_1m: …
```

## Monitoring

- Agent page: live cost + α efficiency
- Agent cycle log: `phase=optimize` shows experiment id (not direct prod apply)
- Compare runs: diff `usage.jsonl` line counts before/after cache warm-up
