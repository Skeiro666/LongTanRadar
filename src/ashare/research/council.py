from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ashare.ai.client import client_for_role, client_from_cfg, parse_json_object
from ashare.config_loaders import load_yaml_config
from ashare.research.intel_package import build_research_intelligence

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
        # map new roles onto existing client role keys when possible
        alias = {"fundamental": "dragon", "quant": "dragon", "valuation": "event", "bear": "risk"}.get(role_id, role_id)
        try:
            client = client_for_role(self.cfg, alias)
        except Exception:  # noqa: BLE001
            client = client_from_cfg(self.cfg)
        intel = build_research_intelligence(snapshot, role_id=role_id)
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
        try:
            text = client.chat(system, json.dumps(payload, ensure_ascii=False, default=str)[:10000], json_mode=True)
            data = parse_json_object(text)
            data["role"] = role_id
            data["prompt_version"] = ver
            data["model"] = getattr(client, "model", "")
            data["status"] = data.get("status") or "ok"
            data["source"] = "llm"
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

    def run_parallel(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        opinions: dict[str, Any] = {}
        parallel = bool((self.research_cfg.get("council") or {}).get("parallel_roles", True))
        if parallel:
            with ThreadPoolExecutor(max_workers=5) as ex:
                futs = {ex.submit(self._call_role, rid, snapshot): rid for rid in self.ROLE_IDS}
                for fut in as_completed(futs):
                    rid = futs[fut]
                    opinions[rid] = fut.result()
        else:
            for rid in self.ROLE_IDS:
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
        intel = snapshot.get("research_intelligence") or build_research_intelligence(snapshot)
        payload = {
            "research_intelligence": {
                "candidate_sources": intel.get("candidate_sources"),
                "research_hypotheses": intel.get("research_hypotheses"),
                "data_availability": intel.get("data_availability"),
                "price_in_risk": intel.get("price_in_risk"),
                "evidence_ids": intel.get("evidence_ids"),
                "rules": intel.get("rules"),
                "quant_context": intel.get("quant_context"),
            },
            "snapshot_quant": snapshot.get("quant"),
            "opinions": opinions,
            "debate": debate,
            "missing_roles": missing,
        }
        try:
            client = client_for_role(self.cfg, "chair")
        except Exception:  # noqa: BLE001
            client = client_from_cfg(self.cfg)
        if getattr(client, "configured", False):
            try:
                text = client.chat(system, json.dumps(payload, ensure_ascii=False, default=str)[:12000], json_mode=True)
                data = parse_json_object(text)
                data["prompt_version"] = ver
                data["model"] = getattr(client, "model", "")
                data["source"] = "llm"
                data.setdefault("trading_action", "WATCH")
                return data
            except Exception as exc:  # noqa: BLE001
                logger.warning("chairman failed: %s", exc)
        return self._heuristic(opinions, missing, ver)

    def _heuristic(self, opinions: dict[str, Any], missing: list[str], ver: str) -> dict[str, Any]:
        scores = [float(v.get("score") or 0) for k, v in opinions.items() if k != "bear" and v.get("status") != "unavailable"]
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
