from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ashare.ai.client import client_for_role, client_from_cfg, parse_json_object
from ashare.config_loaders import load_yaml_config
from ashare.research.cache import compute_context_hash, get_research_cache
from ashare.research.dynamic_council import select_council_roles, skipped_role_opinion
from ashare.research.incremental import roles_to_refresh
from ashare.research.intel_package import build_chairman_context, build_role_context

logger = logging.getLogger("ashare.research.council")


def load_prompts(cfg: dict[str, Any] | None) -> dict[str, Any]:
    return load_yaml_config(cfg, "prompts")


class AICouncilEngine:
    """6-role council. Parallel analysts; failures do not abort session."""

    ROLE_IDS = ("fundamental", "quant", "event", "valuation", "bear")

    def __init__(self, cfg: dict[str, Any] | None = None) -> None:
        self.cfg = cfg or {}
        self.research_cfg = load_yaml_config(self.cfg, "research")
        self.prompts = load_prompts(self.cfg)

    def _prompt_for(self, role_id: str) -> tuple[str, str]:
        roles = list((self.research_cfg.get("council") or {}).get("roles") or [])
        meta = next((r for r in roles if r.get("id") == role_id), {"id": role_id, "prompt_version": f"{role_id}_v1"})
        ver = str(meta.get("prompt_version") or f"{role_id}_v1")
        text = (self.prompts.get("roles") or {}).get(ver) or f"You are {role_id}. Output JSON."
        return ver, text

    def _call_role(self, role_id: str, snapshot: dict[str, Any]) -> dict[str, Any]:
        ver, system = self._prompt_for(role_id)
        if role_id == "valuation" and not snapshot.get("value_available", False):
            return self._heuristic(role_id, snapshot, ver, "unavailable")
        # map new roles onto existing client role keys when possible
        alias = {"fundamental": "dragon", "quant": "dragon", "valuation": "event", "bear": "risk"}.get(role_id, role_id)
        try:
            client = client_for_role(self.cfg, alias)
        except Exception:  # noqa: BLE001
            client = client_from_cfg(self.cfg)
        intel = build_role_context(snapshot, role_id, cfg=self.cfg)
        payload = {
            "symbol": snapshot.get("symbol"),
            "name": snapshot.get("name"),
            "research_intelligence": intel,
            "data_availability": intel.get("data_availability"),
            "research_hypotheses": intel.get("research_hypotheses"),
            "candidate_sources": intel.get("candidate_sources"),
            "value_available": snapshot.get("value_available", False),
            "news_data_incomplete": (snapshot.get("news_package") or {}).get("news_data_incomplete"),
        }
        if not getattr(client, "configured", False):
            return self._heuristic(role_id, snapshot, ver, "unconfigured")

        factor_version = str((self.research_cfg.get("snapshot") or {}).get("factor_version") or "factor_v1")
        payload_json = json.dumps(payload, ensure_ascii=False, default=str)[:10000]
        cache = get_research_cache(self.cfg)
        cache_key = compute_context_hash(
            symbol=str(snapshot.get("symbol") or ""),
            role_id=role_id,
            context=intel,
            prompt_version=ver,
            model=str(getattr(client, "model", "") or ""),
            factor_version=factor_version,
        )
        cached = cache.get(cache_key)
        if cached:
            out = dict(cached)
            out.setdefault("role", role_id)
            out["source"] = "cache"
            try:
                from ashare.ai.cost_tracker import estimate_tokens, get_cost_tracker

                get_cost_tracker(self.cfg).record_cache_save(
                    estimated_tokens=estimate_tokens(system + payload_json),
                    call_site="council.role",
                    role=role_id,
                    symbol=str(snapshot.get("symbol") or "") or None,
                    model=str(getattr(client, "model", "") or ""),
                )
            except Exception:  # noqa: BLE001
                pass
            return out

        try:
            text = client.chat(
                system,
                payload_json,
                json_mode=True,
                role=role_id,
                symbol=str(snapshot.get("symbol") or "") or None,
                call_site="council.role",
            )
            data = parse_json_object(text)
            data["role"] = role_id
            data["prompt_version"] = ver
            data["model"] = getattr(client, "model", "")
            data["status"] = data.get("status") or "ok"
            data["source"] = "llm"
            cache.set(cache_key, data, {"symbol": snapshot.get("symbol"), "role": role_id})
            return data
        except Exception as exc:  # noqa: BLE001
            logger.warning("council role %s failed: %s", role_id, exc)
            out = self._heuristic(role_id, snapshot, ver, "failed")
            out["error"] = str(exc)[:200]
            return out

    def _heuristic(self, role_id: str, snapshot: dict[str, Any], ver: str, status: str) -> dict[str, Any]:
        q = float((snapshot.get("quant") or {}).get("leader_score") or 0)
        ml = float((snapshot.get("quant") or {}).get("ml_prediction") or 0)
        if role_id == "bear":
            score = -0.3 if q > 0.5 else 0.0
            stance = "bear"
        elif role_id == "valuation" and not snapshot.get("value_available", False):
            return {
                "role": role_id,
                "score": 0.0,
                "stance": "neutral",
                "points": ["估值数据不可用"],
                "status": "unavailable",
                "prompt_version": ver,
                "source": "heuristic",
            }
        elif role_id == "event":
            hyps = (snapshot.get("research_intelligence") or {}).get("research_hypotheses") or snapshot.get(
                "research_hypotheses"
            ) or []
            score = 0.15 if hyps else 0.0
            stance = "bull" if score > 0 else "neutral"
            return {
                "role": role_id,
                "score": score,
                "stance": stance,
                "points": [f"heuristic event · hypotheses={len(hyps)}"],
                "facts": [h.get("layers", {}).get("FACT") for h in hyps if isinstance(h, dict)][:3],
                "status": status,
                "prompt_version": ver,
                "source": "heuristic",
            }
        else:
            score = max(-1.0, min(1.0, 0.5 * q + 5 * ml))
            stance = "bull" if score > 0.15 else ("bear" if score < -0.15 else "neutral")
        return {
            "role": role_id,
            "score": score,
            "stance": stance,
            "points": [f"heuristic {role_id}"],
            "top_risks": ["数据不全", "启发式降级"] if role_id == "bear" else [],
            "status": status,
            "prompt_version": ver,
            "source": "heuristic",
        }

    def run_parallel(
        self,
        snapshot: dict[str, Any],
        *,
        prior_snapshot: dict[str, Any] | None = None,
        prior_opinions: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        opinions: dict[str, Any] = {}
        active = select_council_roles(snapshot, self.cfg)
        from ashare.research.incremental import _incremental_cfg

        inc_on = bool(_incremental_cfg(self.cfg).get("enabled", True)) and prior_snapshot is not None
        if inc_on:
            to_call = list(roles_to_refresh(snapshot, prior_snapshot, self.cfg))
        else:
            to_call = list(active)

        for rid in self.ROLE_IDS:
            if rid not in active:
                opinions[rid] = skipped_role_opinion(rid, "dynamic_council: 信号不足，跳过 LLM")

        for rid in active:
            if rid not in to_call and prior_opinions and rid in prior_opinions:
                reused = dict(prior_opinions[rid])
                reused["source"] = "incremental_reuse"
                opinions[rid] = reused

        parallel = bool((self.research_cfg.get("council") or {}).get("parallel_roles", True))
        if parallel:
            with ThreadPoolExecutor(max_workers=5) as ex:
                futs = {ex.submit(self._call_role, rid, snapshot): rid for rid in to_call}
                for fut in as_completed(futs):
                    rid = futs[fut]
                    opinions[rid] = fut.result()
        else:
            for rid in to_call:
                opinions[rid] = self._call_role(rid, snapshot)
        return opinions


class DebateEngine:
    def __init__(self, cfg: dict[str, Any] | None = None) -> None:
        self.cfg = cfg or {}
        self.research_cfg = load_yaml_config(self.cfg, "research")
        self.prompts = load_prompts(self.cfg)

    def needs_debate(self, opinions: dict[str, Any]) -> bool:
        stances = {k: str(v.get("stance") or "neutral") for k, v in opinions.items()}
        bulls = {k for k, s in stances.items() if s == "bull"}
        bears = {k for k, s in stances.items() if s == "bear"}
        return bool(bulls & {"fundamental", "quant", "event"}) and bool(bears)

    def run(self, snapshot: dict[str, Any], opinions: dict[str, Any]) -> list[dict[str, Any]]:
        if not self.needs_debate(opinions):
            return []
        max_rounds = int((self.research_cfg.get("council") or {}).get("max_debate_rounds", 2))
        debates: list[dict[str, Any]] = []
        # deterministic structured debate without extra LLM if unconfigured
        pairs = [("fundamental", "bear"), ("quant", "valuation"), ("event", "bear")]
        for i, (a, b) in enumerate(pairs[:max_rounds]):
            if a not in opinions or b not in opinions:
                continue
            debates.append(
                {
                    "round": i + 1,
                    "from_role": a,
                    "to_role": b,
                    "rebuttal": f"{a} vs {b}: stance {opinions[a].get('stance')} vs {opinions[b].get('stance')}",
                    "evidence": (opinions[a].get("points") or [])[:2],
                    "change_condition": opinions[a].get("falsify") or "数据证伪",
                    "prompt_version": "debate_v1",
                }
            )
        return debates


class ChairmanEngine:
    def __init__(self, cfg: dict[str, Any] | None = None) -> None:
        self.cfg = cfg or {}
        self.prompts = load_prompts(self.cfg)

    def summarize(
        self,
        snapshot: dict[str, Any],
        opinions: dict[str, Any],
        debate: list[dict[str, Any]],
    ) -> dict[str, Any]:
        ver = "chairman_v1"
        system = (self.prompts.get("roles") or {}).get(ver) or "Chairman. Output JSON."
        missing = [k for k, v in opinions.items() if v.get("status") in {"failed", "unavailable"}]
        payload = build_chairman_context(snapshot, opinions, debate, cfg=self.cfg)
        try:
            client = client_for_role(self.cfg, "chair")
        except Exception:  # noqa: BLE001
            client = client_from_cfg(self.cfg)
        if getattr(client, "configured", False):
            factor_version = str((load_yaml_config(self.cfg, "research").get("snapshot") or {}).get("factor_version") or "factor_v1")
            cache = get_research_cache(self.cfg)
            opinion_sig = {
                k: {"score": v.get("score"), "stance": v.get("stance"), "status": v.get("status")}
                for k, v in opinions.items()
                if isinstance(v, dict)
            }
            cache_key = compute_context_hash(
                symbol=str(snapshot.get("symbol") or ""),
                role_id="chairman",
                context={"intel": payload.get("research_intelligence"), "opinions": opinion_sig, "debate": debate},
                prompt_version=ver,
                model=str(getattr(client, "model", "") or ""),
                factor_version=factor_version,
            )
            cached = cache.get(cache_key)
            if cached:
                out = dict(cached)
                out["source"] = "cache"
                return out
            try:
                text = client.chat(
                    system,
                    json.dumps(payload, ensure_ascii=False, default=str)[:12000],
                    json_mode=True,
                    role="chairman",
                    symbol=str(snapshot.get("symbol") or "") or None,
                    call_site="council.chairman",
                )
                data = parse_json_object(text)
                data["prompt_version"] = ver
                data["model"] = getattr(client, "model", "")
                data["source"] = "llm"
                data.setdefault("trading_action", "WATCH")
                cache.set(cache_key, data, {"symbol": snapshot.get("symbol"), "role": "chairman"})
                return data
            except Exception as exc:  # noqa: BLE001
                logger.warning("chairman failed: %s", exc)
        return self._heuristic(opinions, missing, ver)

    def _heuristic(self, opinions: dict[str, Any], missing: list[str], ver: str) -> dict[str, Any]:
        scores = [
            float(v.get("score") or 0)
            for k, v in opinions.items()
            if k != "bear" and v.get("status") not in {"unavailable", "skipped", "failed"}
        ]
        bear = float((opinions.get("bear") or {}).get("score") or 0)
        avg = float(sum(scores) / len(scores)) if scores else 0.0
        if avg > 0.4 and bear > -0.5:
            rating, action = "BUY", "WAIT_FOR_CONFIRMATION"
        elif avg > 0.15:
            rating, action = "WATCH", "WATCH"
        elif avg < -0.3 or bear < -0.6:
            rating, action = "AVOID", "NO_ACTION"
        else:
            rating, action = "NEUTRAL", "WATCH"
        return {
            "rating": rating,
            "confidence": 0.45,
            "bull_case": "启发式综合多头角色",
            "base_case": "观望确认",
            "bear_case": "空头角色提示风险",
            "catalysts": [],
            "risks": (opinions.get("bear") or {}).get("top_risks") or ["启发式"],
            "invalidation_conditions": ["跌破关键均线", "催化证伪"],
            "monitoring_indicators": ["成交额", "相对强度", "事件兑现"],
            "time_horizon": "5-20D",
            "trading_action": action,
            "position_suggestion": 0.0,
            "missing_roles": missing,
            "prompt_version": ver,
            "source": "heuristic",
            "status": "ok",
        }
