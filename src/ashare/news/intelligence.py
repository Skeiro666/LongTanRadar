from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable

from ashare.ai.client import LLMClient, parse_json_object
from ashare.ai.cost_tracker import estimate_tokens
from ashare.news.intel_cache import NewsIntelCache, content_hash
from ashare.news.intel_score import news_intelligence_score
from ashare.news.models import RawNews
from ashare.news.schema import (
    PROMPT_VERSION_ENTITY,
    PROMPT_VERSION_INTEL,
    clamp01,
    normalize_direction,
    normalize_event_type,
    normalize_horizon,
    strip_trade_actions,
)
from ashare.news.score import source_quality

logger = logging.getLogger("ashare.news.intelligence")

_INTEL_SYSTEM = """你是 A 股新闻理解引擎（本地，不交易）。
只理解新闻。禁止 BUY/SELL/STRONG_BUY/仓位/最终评级/交易动作。
只输出一个 JSON 对象，字段：
event_type, direction, importance, novelty, market_relevance, impact_horizon,
event_confidence, summary, evidence, hypothesis, beneficiary_industries
event_type 只能是：earnings, earnings_preannouncement, contract, order, merger, acquisition, restructuring, share_buyback, shareholder_reduction, shareholder_increase, executive_change, dividend, financing, litigation, regulatory, product, capacity, policy, industry, supply_chain, guidance, other, unknown
direction 只能是：positive, negative, neutral, mixed, unknown
impact_horizon 只能是：intraday, short, medium, long, unknown
importance/novelty/market_relevance/event_confidence 为 0 到 1 的数字。
evidence 是字符串数组，必须来自原文事实。
没有明确公司时填写 hypothesis 与 beneficiary_industries；有明确公司时 hypothesis 可为空字符串。"""

_ENTITY_SYSTEM = """你是 A 股新闻实体映射助手（本地，不交易）。
根据标题和摘要，推断最可能相关或受益的 A 股上市公司。
硬规则：
1. 只输出 JSON：{"beneficiaries":[{"symbol":"600519.SH","name":"...","confidence":0.3}]}
2. confidence 不得超过 0.45
3. 不确定则 beneficiaries 为空
4. 禁止编造代码；只映射 A 股
5. 禁止 BUY/SELL/仓位"""


class NewsTokenBudget:
    def __init__(self, max_tokens: int) -> None:
        self.max_tokens = int(max_tokens)
        self.used = 0

    def allow(self, estimate: int) -> bool:
        if self.max_tokens <= 0:
            return True
        return self.used + estimate <= self.max_tokens

    def add(self, n: int) -> None:
        self.used += max(0, int(n))


def _sanitize_intel(raw: dict[str, Any], *, news: RawNews, entity_confidence: float) -> dict[str, Any]:
    evidence = raw.get("evidence") or []
    if isinstance(evidence, str):
        evidence = [evidence]
    evidence = [strip_trade_actions(str(x))[:300] for x in evidence if str(x).strip()][:8]
    industries = raw.get("beneficiary_industries") or []
    if isinstance(industries, str):
        industries = [industries]
    industries = [str(x)[:40] for x in industries if str(x).strip()][:8]
    q = source_quality(news)
    out = {
        "event_type": normalize_event_type(raw.get("event_type")),
        "direction": normalize_direction(raw.get("direction")),
        "importance": clamp01(raw.get("importance"), 0.0),
        "novelty": clamp01(raw.get("novelty"), 0.0),
        "market_relevance": clamp01(raw.get("market_relevance"), 0.0),
        "impact_horizon": normalize_horizon(raw.get("impact_horizon")),
        "event_confidence": clamp01(raw.get("event_confidence"), 0.0),
        "summary": strip_trade_actions(str(raw.get("summary") or news.title))[:280],
        "evidence": evidence or [news.title[:180]],
        "hypothesis": strip_trade_actions(str(raw.get("hypothesis") or "")),
        "beneficiary_industries": industries,
    }
    out["news_intelligence_score"] = news_intelligence_score(
        importance=out["importance"],
        novelty=out["novelty"],
        market_relevance=out["market_relevance"],
        event_confidence=out["event_confidence"],
        entity_confidence=entity_confidence,
        source_quality=q,
    )
    return out


def _empty_intel(news: RawNews, *, entity_confidence: float, reason: str) -> dict[str, Any]:
    q = source_quality(news)
    return {
        "event_type": "unknown",
        "direction": "unknown",
        "importance": 0.0,
        "novelty": 0.0,
        "market_relevance": 0.0,
        "impact_horizon": "unknown",
        "event_confidence": 0.0,
        "summary": "",
        "evidence": [],
        "hypothesis": "",
        "beneficiary_industries": [],
        "news_intelligence_score": news_intelligence_score(
            importance=0,
            novelty=0,
            market_relevance=0,
            event_confidence=0,
            entity_confidence=entity_confidence,
            source_quality=q,
        ),
        "fallback_reason": reason,
    }


class LocalNewsIntelligence:
    """Local LLM news understanding. Never calls Council / Chair / Risk."""

    def __init__(
        self,
        cfg: dict[str, Any] | None,
        client: LLMClient | None,
        *,
        cache: NewsIntelCache | None = None,
    ) -> None:
        self.cfg = cfg or {}
        self.client = client
        news_cfg: dict[str, Any] = {}
        try:
            from ashare.config_loaders import load_yaml_config

            news_cfg = dict(load_yaml_config(self.cfg, "news") or {})
        except Exception:  # noqa: BLE001
            news_cfg = dict((self.cfg.get("news") or {}) if isinstance(self.cfg.get("news"), dict) else {})
        self.news_cfg = news_cfg
        intel_cfg = dict(news_cfg.get("intelligence") or {})
        self.max_concurrency = max(1, int(intel_cfg.get("max_concurrency") or 2))
        self.max_retries = max(0, int(intel_cfg.get("max_retries") or 1))
        self.max_per_cycle = int(intel_cfg.get("max_llm_per_cycle") or 24)
        self._llm_calls = 0
        root = Path(self.cfg.get("_root") or Path(__file__).resolve().parents[3])
        self.cache = cache or NewsIntelCache(root)
        self.model_name = str((client.model if client else "") or (news_cfg.get("llm") or {}).get("model") or "")
        self._budget = NewsTokenBudget(int(intel_cfg.get("max_tokens_per_cycle") or 80_000))

    @property
    def available(self) -> bool:
        return bool(self.client is not None and getattr(self.client, "configured", False))

    def extract_intelligence(
        self,
        news: RawNews,
        *,
        symbol: str = "",
        entity_confidence: float = 0.0,
    ) -> dict[str, Any]:
        chash = content_hash(news.title, news.summary, news.content)
        meta = {
            "news_id": news.id,
            "content_hash": chash,
            "model": self.model_name,
            "prompt_version": PROMPT_VERSION_INTEL,
            "task": "intelligence",
        }
        cached = self.cache.get(
            news_id=news.id,
            content_hash=chash,
            model=self.model_name,
            prompt_version=PROMPT_VERSION_INTEL,
        )
        if cached and cached.get("result"):
            result = dict(cached["result"])
            result["cache_hit"] = True
            result["model_name"] = cached.get("model") or self.model_name
            result["prompt_version"] = PROMPT_VERSION_INTEL
            result["input_tokens"] = int(cached.get("input_tokens") or 0)
            result["output_tokens"] = int(cached.get("output_tokens") or 0)
            result["total_tokens"] = int(cached.get("total_tokens") or 0)
            result["latency_ms"] = float(cached.get("latency_ms") or 0)
            result["usage_source"] = str(cached.get("usage_source") or "cache")
            try:
                from ashare.ai.cost_tracker import get_cost_tracker

                saved = int(result.get("total_tokens") or 0) or 200
                get_cost_tracker().record_cache_save(
                    estimated_tokens=saved,
                    call_site="news_intelligence",
                    symbol=symbol or None,
                    role="news_intel",
                    model=self.model_name,
                )
            except Exception:  # noqa: BLE001
                pass
            return result

        if not self.available:
            empty = _empty_intel(news, entity_confidence=entity_confidence, reason="llm_unavailable")
            empty.update({**meta, "cache_hit": False, "status": "skipped"})
            return empty

        if self._llm_calls >= self.max_per_cycle:
            empty = _empty_intel(news, entity_confidence=entity_confidence, reason="max_llm_per_cycle")
            empty.update({**meta, "cache_hit": False, "status": "skipped"})
            return empty

        est = estimate_tokens(news.title + (news.summary or "")[:400]) + 400
        if not self._budget.allow(est):
            empty = _empty_intel(news, entity_confidence=entity_confidence, reason="token_budget")
            empty.update({**meta, "cache_hit": False, "status": "budget"})
            return empty

        body = (news.summary or news.content or "")[:800]
        known = f"已知股票：{symbol}" if symbol else "已知股票：无"
        user = f"{known}\n标题：{news.title}\n摘要：{body}\n只输出 JSON。"
        t0 = time.perf_counter()
        parsed: dict[str, Any] | None = None
        last_err = ""
        self._llm_calls += 1
        for attempt in range(self.max_retries + 1):
            try:
                raw = self.client.chat(  # type: ignore[union-attr]
                    _INTEL_SYSTEM,
                    user,
                    json_mode=True,
                    call_site="news_intelligence",
                    role="news_intel",
                    symbol=symbol or None,
                )
                parsed = parse_json_object(raw)
                break
            except Exception as exc:  # noqa: BLE001
                last_err = str(exc)[:200]
                logger.warning("news intelligence failed id=%s attempt=%s: %s", news.id, attempt, exc)
        latency = (time.perf_counter() - t0) * 1000.0
        inp = estimate_tokens(_INTEL_SYSTEM + user)
        out_n = estimate_tokens(str(parsed or last_err))
        self._budget.add(inp + out_n)
        usage = {
            "input_tokens": inp,
            "output_tokens": out_n,
            "total_tokens": inp + out_n,
            "latency_ms": round(latency, 1),
            "usage_source": "estimated",
            "model_name": self.model_name,
            "prompt_version": PROMPT_VERSION_INTEL,
        }
        if parsed is None:
            empty = _empty_intel(news, entity_confidence=entity_confidence, reason="json_or_ollama_failure")
            empty.update({**meta, "cache_hit": False, "status": "error", "error": last_err, **usage})
            self.cache.put({**meta, "result": empty, "status": "error", **usage})
            return empty

        intel = _sanitize_intel(parsed, news=news, entity_confidence=entity_confidence)
        intel.update({**meta, "cache_hit": False, "status": "ok", **usage})
        self.cache.put({**meta, "result": intel, "status": "ok", **usage})
        return intel

    def infer_entities(self, news: RawNews, *, max_guesses: int = 3) -> list[dict[str, Any]]:
        if not self.available:
            return []
        chash = content_hash(news.title, news.summary, news.content)
        cached = self.cache.get(
            news_id=news.id + ":ent",
            content_hash=chash,
            model=self.model_name,
            prompt_version=PROMPT_VERSION_ENTITY,
        )
        if cached and isinstance(cached.get("result"), list):
            return list(cached["result"])
        body = (news.summary or news.content or "")[:400]
        user = f"标题：{news.title}\n摘要：{body}\n输出 JSON。"
        try:
            raw = self.client.chat(  # type: ignore[union-attr]
                _ENTITY_SYSTEM,
                user,
                json_mode=True,
                call_site="news_llm_mapping",
                role="news_entity",
            )
            data = parse_json_object(raw)
            guesses = list(data.get("beneficiaries") or data.get("stocks") or [])[:max_guesses]
        except Exception as exc:  # noqa: BLE001
            logger.warning("news entity mapping failed for %s: %s", news.id, exc)
            guesses = []
        self.cache.put(
            {
                "news_id": news.id + ":ent",
                "content_hash": chash,
                "model": self.model_name,
                "prompt_version": PROMPT_VERSION_ENTITY,
                "result": guesses,
                "status": "ok" if guesses else "empty",
                "task": "entity",
            }
        )
        return guesses

    def map_batch(
        self,
        items: list[RawNews],
        fn: Callable[[RawNews], dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        """Bounded parallel LLM calls. Never unbounded Ollama fan-out."""
        out: dict[str, dict[str, Any]] = {}
        if not items:
            return out
        workers = min(self.max_concurrency, len(items))
        subset = items[: self.max_per_cycle]
        if workers <= 1:
            for n in subset:
                out[n.id] = fn(n)
            return out
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(fn, n): n for n in subset}
            for fut in as_completed(futs):
                n = futs[fut]
                try:
                    out[n.id] = fut.result()
                except Exception as exc:  # noqa: BLE001
                    logger.warning("intel worker failed %s: %s", n.id, exc)
                    out[n.id] = _empty_intel(n, entity_confidence=0.0, reason="worker_error")
        return out
