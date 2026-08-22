from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from ashare.config_loaders import load_yaml_config
from ashare.research.intel_package import build_research_intelligence


def _candidate_score_meta(candidate: dict[str, Any]) -> dict[str, Any]:
    hyps = list(candidate.get("research_hypotheses") or [])
    inv = dict((candidate.get("news_discovery") or {}).get("investment_hypothesis") or {})
    if not inv and hyps and isinstance(hyps[0], dict):
        inv = dict(hyps[0].get("investment_hypothesis") or {})
    eer = dict(inv.get("expected_excess_return") or {})
    if not eer.get("available"):
        eer = {
            "available": False,
            "value": None,
            "confidence": 0.0,
            "horizon": inv.get("mechanism") or "unknown",
            "note": "无可靠 expected_excess_return，禁止伪造",
            "qualitative_only": True,
        }
    return {
        "candidate_score": round(float(candidate.get("candidate_score") or 0), 6),
        "semantic": "cross_sectional_ranking_score",
        "not_probability": True,
        "not_expected_return": True,
        "expected_excess_return": eer,
        "confidence": float(eer.get("confidence") or 0.0) if eer.get("available") else None,
    }


class SnapshotStore:
    def __init__(self, cfg: dict[str, Any] | None = None) -> None:
        self.cfg = cfg or {}
        root = Path(self.cfg.get("_root") or Path(__file__).resolve().parents[2])
        self.dir = root / "data" / "research_snapshots"
        self.dir.mkdir(parents=True, exist_ok=True)

    def save(self, snapshot: dict[str, Any]) -> Path:
        rid = snapshot.get("research_id") or f"R{datetime.now().strftime('%Y%m%d%H%M%S')}"
        path = self.dir / f"{rid}.json"
        path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        sym = snapshot.get("symbol")
        if sym:
            sym_path = self.dir / f"_latest_{sym}.json"
            sym_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        return path

    def load_latest_for_symbol(self, symbol: str) -> dict[str, Any] | None:
        sym_path = self.dir / f"_latest_{symbol}.json"
        if sym_path.exists():
            try:
                return json.loads(sym_path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                pass
        return None


def build_snapshot(candidate: dict[str, Any], cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    research_cfg = load_yaml_config(cfg, "research")
    snap_cfg = dict(research_cfg.get("snapshot") or {})
    rid = f"R{datetime.now(timezone.utc).strftime('%Y%m%d')}" + uuid4().hex[:6].upper()
    snap = {
        "research_id": rid,
        "symbol": candidate.get("symbol"),
        "name": candidate.get("name"),
        "research_time": datetime.now(timezone.utc).isoformat(),
        "snapshot_time": datetime.now(timezone.utc).isoformat(),
        "versions": {
            "factor_version": snap_cfg.get("factor_version") or candidate.get("factor_version") or "factor_v1",
            "prompt_bundle": snap_cfg.get("prompt_bundle") or "prompts_v1",
            "model_bundle": snap_cfg.get("model_bundle") or "models_v1",
            "research_version": research_cfg.get("research_version") or "research_v1",
        },
        "trigger": candidate.get("trigger") or {},
        "quant": {
            "factor_score": candidate.get("candidate_score"),
            "leader_score": candidate.get("leader_score"),
            "ml_prediction": candidate.get("ml_prediction"),
            "momentum_score": candidate.get("score_momentum"),
            "relative_strength_score": candidate.get("score_relative_strength"),
            "value_score": candidate.get("score_value"),
            "quality_score": candidate.get("score_quality"),
            "liquidity_score": candidate.get("score_liquidity"),
            "breakout_score": candidate.get("score_breakout"),
            "factors": candidate.get("factors") or {},
        },
        "profit_inflection": candidate.get("profit_inflection") or {},
        "event": candidate.get("event") or {"score": candidate.get("event_score"), "events": candidate.get("events") or []},
        "market": {
            "price": candidate.get("close") or candidate.get("price"),
            "amount": candidate.get("amount"),
            "pct_chg": candidate.get("pct_chg"),
        },
        "value_available": bool(candidate.get("value_available", False)),
        "quality_available": bool(candidate.get("quality_available", False)),
        "market_regime": candidate.get("market_regime") or "UNKNOWN",
        "candidate_sources": list(candidate.get("candidate_sources") or []),
        "research_hypotheses": list(candidate.get("research_hypotheses") or []),
        "news_discovery": candidate.get("news_discovery") or {},
        "price_reaction": (candidate.get("news_discovery") or {}).get("price_reaction")
        or candidate.get("price_reaction")
        or {"available": False, "note": "no_bars_or_not_computed"},
        "price_in_risk": candidate.get("price_in_risk")
        or (candidate.get("news_discovery") or {}).get("price_in_risk")
        or "UNKNOWN",
        "news_package": candidate.get("news_package") or {},
        "candidate_score_meta": _candidate_score_meta(candidate),
        "news_snapshot": {
            "news_ids": (candidate.get("news_package") or {}).get("news_ids") or [],
            "event_ids": (candidate.get("news_package") or {}).get("event_ids") or [],
            "news_data_version": ((candidate.get("news_package") or {}).get("versions") or {}).get("news_data_version"),
            "event_engine_version": ((candidate.get("news_package") or {}).get("versions") or {}).get(
                "event_engine_version"
            ),
            "provider_version": ((candidate.get("news_package") or {}).get("versions") or {}).get("provider_version"),
            "news_data_incomplete": (candidate.get("news_package") or {}).get("news_data_incomplete"),
        },
    }
    snap["research_intelligence"] = build_research_intelligence(snap)
    return snap
