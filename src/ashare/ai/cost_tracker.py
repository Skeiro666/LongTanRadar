from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


def estimate_tokens(text: str) -> int:
    """Rough token count for mixed CN/EN text when provider usage is missing."""
    if not text:
        return 0
    cjk = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    other = len(text) - cjk
    return max(1, int(cjk / 1.5 + other / 4))


def estimate_cost_usd(
    model: str,
    input_tokens: int,
    output_tokens: int,
    rates: dict[str, Any] | None = None,
) -> float:
    """USD estimate from per-1M-token rates in config."""
    rates = rates or {}
    default_in = float(rates.get("default_input_per_1m") or 0.5)
    default_out = float(rates.get("default_output_per_1m") or 1.5)
    model_rates = (rates.get("models") or {}).get(model) or {}
    in_rate = float(model_rates.get("input_per_1m") or default_in)
    out_rate = float(model_rates.get("output_per_1m") or default_out)
    return (input_tokens / 1_000_000.0) * in_rate + (output_tokens / 1_000_000.0) * out_rate


@dataclass
class LLMUsageRecord:
    request_id: str
    timestamp: str
    cycle_id: str | None
    research_session_id: str | None
    symbol: str | None
    role: str | None
    call_site: str | None
    model: str
    provider: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    latency_ms: float
    cache_hit: bool
    usage_source: str  # actual | estimated | cache
    estimated_cost_usd: float
    cache_saved_tokens: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class _CycleBucket:
    cycle_id: str
    records: list[LLMUsageRecord] = field(default_factory=list)
    cache_saved_tokens: int = 0


class AICostTracker:
    """Append-only LLM usage log + in-memory cycle/daily rollups."""

    def __init__(self, cfg: dict[str, Any] | None = None) -> None:
        self.cfg = cfg or {}
        ai = self.cfg.get("ai") or {}
        ct = dict(ai.get("cost_tracking") or {})
        root = Path(self.cfg.get("_root") or Path(__file__).resolve().parents[2])
        self.enabled = bool(ct.get("enabled", True))
        self.log_path = root / str(ct.get("log_path") or "data/ai/usage.jsonl")
        self.rates = dict(ct.get("usd_per_1m") or {})
        self._lock = threading.Lock()
        self._cycle: _CycleBucket | None = None
        self._daily: dict[str, list[LLMUsageRecord]] = {}

    def begin_cycle(self, cycle_id: str) -> None:
        with self._lock:
            self._cycle = _CycleBucket(cycle_id=str(cycle_id))

    def current_cycle_id(self) -> str | None:
        with self._lock:
            return self._cycle.cycle_id if self._cycle else None

    def record(
        self,
        *,
        model: str,
        provider: str,
        input_tokens: int,
        output_tokens: int,
        latency_ms: float,
        usage_source: str,
        symbol: str | None = None,
        role: str | None = None,
        call_site: str | None = None,
        cache_hit: bool = False,
        cycle_id: str | None = None,
        research_session_id: str | None = None,
    ) -> LLMUsageRecord:
        total = int(input_tokens + output_tokens)
        rec = LLMUsageRecord(
            request_id=uuid4().hex[:16].upper(),
            timestamp=datetime.now(timezone.utc).isoformat(),
            cycle_id=cycle_id or self.current_cycle_id(),
            research_session_id=research_session_id,
            symbol=symbol,
            role=role,
            call_site=call_site,
            model=model,
            provider=provider,
            input_tokens=int(input_tokens),
            output_tokens=int(output_tokens),
            total_tokens=total,
            latency_ms=float(latency_ms),
            cache_hit=bool(cache_hit),
            usage_source=str(usage_source),
            estimated_cost_usd=round(
                estimate_cost_usd(model, input_tokens, output_tokens, self.rates), 8
            ),
        )
        if not self.enabled:
            return rec
        with self._lock:
            if self._cycle and rec.cycle_id == self._cycle.cycle_id:
                self._cycle.records.append(rec)
            day = date.fromisoformat(rec.timestamp[:10])
            self._daily.setdefault(day.isoformat(), []).append(rec)
        self._append_jsonl(rec)
        return rec

    def record_cache_save(
        self,
        *,
        estimated_tokens: int,
        call_site: str,
        symbol: str | None = None,
        role: str | None = None,
        model: str = "",
        cycle_id: str | None = None,
    ) -> None:
        """Account for tokens not spent because a cache hit skipped the LLM call."""
        if not self.enabled or estimated_tokens <= 0:
            return
        cid = cycle_id or self.current_cycle_id()
        rec = LLMUsageRecord(
            request_id=uuid4().hex[:16].upper(),
            timestamp=datetime.now(timezone.utc).isoformat(),
            cycle_id=cid,
            research_session_id=None,
            symbol=symbol,
            role=role,
            call_site=call_site,
            model=model or "cache",
            provider="cache",
            input_tokens=0,
            output_tokens=0,
            total_tokens=0,
            latency_ms=0.0,
            cache_hit=True,
            usage_source="cache",
            estimated_cost_usd=0.0,
            cache_saved_tokens=int(estimated_tokens),
        )
        if self.enabled:
            with self._lock:
                if self._cycle and rec.cycle_id == self._cycle.cycle_id:
                    self._cycle.records.append(rec)
                day = date.fromisoformat(rec.timestamp[:10])
                self._daily.setdefault(day.isoformat(), []).append(rec)
            self._append_jsonl(rec)

    def cycle_summary(self, cycle_id: str | None = None) -> dict[str, Any]:
        with self._lock:
            bucket = self._cycle
            if cycle_id and (not bucket or bucket.cycle_id != cycle_id):
                bucket = None
            records = list(bucket.records) if bucket else []
            cache_saved = int(bucket.cache_saved_tokens) if bucket else 0
        return self._summarize_records(records, cache_saved_tokens=cache_saved, label="cycle")

    def daily_summary(self, day: str | None = None) -> dict[str, Any]:
        day = day or date.today().isoformat()
        with self._lock:
            records = list(self._daily.get(day) or [])
        return self._summarize_records(records, label=f"daily:{day}")

    def summary(self, *, context: dict[str, Any] | None = None) -> dict[str, Any]:
        today = date.today().isoformat()
        with self._lock:
            all_today = list(self._daily.get(today) or [])
            cycle = self.cycle_summary() if self._cycle else {"n_calls": 0}
        daily = self._summarize_records(all_today, label=f"daily:{today}")
        out = {
            "enabled": self.enabled,
            "log_path": str(self.log_path),
            "cycle_cost": cycle,
            "daily_cost": daily,
            "cycle": cycle,
            "daily": daily,
        }
        if context:
            out["efficiency"] = self.efficiency_metrics(cycle, context)
        return out

    def efficiency_metrics(self, cycle_summary: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        """Per-candidate / per-research / per-buy cost efficiency."""
        n_candidates = int(context.get("n_candidates") or 0)
        n_research = int(context.get("n_research") or context.get("n_council") or 0)
        n_buys = int(context.get("n_buys") or 0)
        total_tokens = int(cycle_summary.get("total_tokens") or 0)
        cost = float(cycle_summary.get("estimated_usd") or 0)
        n_calls = int(cycle_summary.get("n_calls") or 0)
        cache_hits = int(cycle_summary.get("n_cache_events") or 0)
        saved = int(cycle_summary.get("cache_saved_tokens") or 0)
        denom = lambda n: n if n > 0 else None
        return {
            "total_calls": n_calls,
            "input_tokens": cycle_summary.get("input_tokens", 0),
            "output_tokens": cycle_summary.get("output_tokens", 0),
            "total_tokens": total_tokens,
            "cache_hits": cache_hits,
            "cache_saved_tokens": saved,
            "cache_hit_rate": round(cache_hits / n_calls, 4) if n_calls else 0.0,
            "estimated_usd": cost,
            "tokens_per_candidate": round(total_tokens / n_candidates, 1) if denom(n_candidates) else None,
            "tokens_per_research": round(total_tokens / n_research, 1) if denom(n_research) else None,
            "tokens_per_buy": round(total_tokens / n_buys, 1) if denom(n_buys) else None,
            "cost_per_candidate": round(cost / n_candidates, 6) if denom(n_candidates) else None,
            "cost_per_buy": round(cost / n_buys, 6) if denom(n_buys) else None,
            "context": {
                "n_candidates": n_candidates,
                "n_research": n_research,
                "n_buys": n_buys,
            },
        }

    def _summarize_records(
        self,
        records: list[LLMUsageRecord],
        *,
        cache_saved_tokens: int = 0,
        label: str = "",
    ) -> dict[str, Any]:
        llm_calls = [r for r in records if r.usage_source != "cache" and not r.cache_hit]
        cache_rows = [r for r in records if r.cache_saved_tokens > 0]
        saved = cache_saved_tokens + sum(r.cache_saved_tokens for r in cache_rows)
        in_tok = sum(r.input_tokens for r in llm_calls)
        out_tok = sum(r.output_tokens for r in llm_calls)
        cost = sum(r.estimated_cost_usd for r in llm_calls)
        by_role: dict[str, int] = {}
        by_model: dict[str, int] = {}
        by_symbol: dict[str, int] = {}
        role_cost: dict[str, float] = {}
        model_cost: dict[str, float] = {}
        symbol_cost: dict[str, float] = {}
        for r in llm_calls:
            by_role[r.role or "unknown"] = by_role.get(r.role or "unknown", 0) + r.total_tokens
            by_model[r.model or "unknown"] = by_model.get(r.model or "unknown", 0) + r.total_tokens
            role_cost[r.role or "unknown"] = role_cost.get(r.role or "unknown", 0.0) + r.estimated_cost_usd
            model_cost[r.model or "unknown"] = model_cost.get(r.model or "unknown", 0.0) + r.estimated_cost_usd
            if r.symbol:
                by_symbol[r.symbol] = by_symbol.get(r.symbol, 0) + r.total_tokens
                symbol_cost[r.symbol] = symbol_cost.get(r.symbol, 0.0) + r.estimated_cost_usd
        n_sym = len({r.symbol for r in llm_calls if r.symbol}) or 0
        cache_hit_calls = sum(1 for r in records if r.cache_hit and r.usage_source != "cache")
        return {
            "label": label,
            "n_calls": len(llm_calls),
            "total_calls": len(llm_calls),
            "n_cache_events": len(cache_rows),
            "cache_hits": cache_hit_calls + len(cache_rows),
            "input_tokens": in_tok,
            "output_tokens": out_tok,
            "total_tokens": in_tok + out_tok,
            "estimated_usd": round(cost, 6),
            "cache_saved_tokens": saved,
            "latency_ms_total": round(sum(r.latency_ms for r in llm_calls), 1),
            "tokens_per_call": round((in_tok + out_tok) / len(llm_calls), 1) if llm_calls else 0,
            "tokens_per_symbol": round((in_tok + out_tok) / n_sym, 1) if n_sym else 0,
            "by_role": by_role,
            "by_model": by_model,
            "by_symbol": by_symbol,
            "role_cost": {k: round(v, 6) for k, v in role_cost.items()},
            "model_cost": {k: round(v, 6) for k, v in model_cost.items()},
            "symbol_cost": {k: round(v, 6) for k, v in symbol_cost.items()},
            "actual_usage_calls": sum(1 for r in llm_calls if r.usage_source == "actual"),
            "estimated_usage_calls": sum(1 for r in llm_calls if r.usage_source == "estimated"),
        }

    def _append_jsonl(self, rec: LLMUsageRecord) -> None:
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec.to_dict(), ensure_ascii=False) + "\n")
        except Exception:  # noqa: BLE001
            pass

    def load_recent(self, limit: int = 50) -> list[dict[str, Any]]:
        if not self.log_path.exists():
            return []
        lines = self.log_path.read_text(encoding="utf-8").splitlines()
        out: list[dict[str, Any]] = []
        for line in lines[-limit:]:
            try:
                out.append(json.loads(line))
            except Exception:  # noqa: BLE001
                continue
        return out


_tracker_singleton: AICostTracker | None = None
_tracker_lock = threading.Lock()


def get_cost_tracker(cfg: dict[str, Any] | None = None) -> AICostTracker:
    global _tracker_singleton
    with _tracker_lock:
        if cfg is not None:
            _tracker_singleton = AICostTracker(cfg)
        elif _tracker_singleton is None:
            _tracker_singleton = AICostTracker({})
        return _tracker_singleton


# V5 alias — single ledger entry point
AICostLedger = AICostTracker
