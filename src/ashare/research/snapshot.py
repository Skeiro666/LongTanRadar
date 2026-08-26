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
        self.rev_index = self.dir / "_revisions.jsonl"

    def save(self, snapshot: dict[str, Any]) -> Path:
        rid = snapshot.get("research_id") or f"R{datetime.now().strftime('%Y%m%d%H%M%S')}"
        path = self.dir / f"{rid}.json"
        # Never overwrite an existing snapshot file — bump id if collision
        if path.exists():
            rid = f"R{datetime.now(timezone.utc).strftime('%Y%m%d')}{uuid4().hex[:6].upper()}"
            snapshot["research_id"] = rid
            path = self.dir / f"{rid}.json"
        path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        sym = snapshot.get("symbol")
        if sym:
            sym_path = self.dir / f"_latest_{sym}.json"
            sym_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
            # Formal day pointer (latest revision for symbol+research_date)
            day = str(snapshot.get("research_date") or snapshot.get("as_of") or "")[:10]
            if day:
                day_ptr = self.dir / f"_formal_{sym}_{day}.json"
                day_ptr.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        with self.rev_index.open("a", encoding="utf-8") as f:
            f.write(
                json.dumps(
                    {
                        "snapshot_id": rid,
                        "research_id": rid,
                        "symbol": snapshot.get("symbol"),
                        "research_date": snapshot.get("research_date") or snapshot.get("as_of"),
                        "revision": snapshot.get("revision", 1),
                        "trigger": snapshot.get("revision_trigger") or snapshot.get("trigger"),
                        "created_at": snapshot.get("research_time") or datetime.now(timezone.utc).isoformat(),
                    },
                    ensure_ascii=False,
                    default=str,
                )
                + "\n"
            )
        return path

    def load_latest_for_symbol(self, symbol: str) -> dict[str, Any] | None:
        sym_path = self.dir / f"_latest_{symbol}.json"
        if sym_path.exists():
            try:
                return json.loads(sym_path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                pass
        return None

    def load_formal_for_date(self, symbol: str, research_date: str) -> dict[str, Any] | None:
        """Immutable formal ResearchSnapshot for symbol+date (latest revision pointer)."""
        day = str(research_date)[:10]
        ptr = self.dir / f"_formal_{symbol}_{day}.json"
        if ptr.exists():
            try:
                return json.loads(ptr.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                pass
        # Fallback: scan R*.json
        best: dict[str, Any] | None = None
        best_rev = -1
        for p in self.dir.glob("R*.json"):
            try:
                raw = json.loads(p.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
            if str(raw.get("symbol") or "") != str(symbol):
                continue
            if str(raw.get("research_date") or raw.get("as_of") or "")[:10] != day:
                continue
            rev = int(raw.get("revision") or 1)
            if rev > best_rev:
                best_rev = rev
                best = raw
        return best

    def next_revision(self, symbol: str, research_date: str) -> int:
        cur = self.load_formal_for_date(symbol, research_date)
        if not cur:
            return 1
        return int(cur.get("revision") or 1) + 1


REASSESSMENT_TRIGGERS = frozenset(
    {
        "BREAK_LIMIT",
        "BREAK_LIMIT_PERSISTED",
        "STATE_RECOVERED",
        "MANUAL_REASSESSMENT",
        "EXPLICIT_REASSESSMENT",
    }
)


def reassessment_trigger_of(candidate: dict[str, Any]) -> str | None:
    for key in ("reassessment_trigger", "revision_trigger", "explicit_reassessment"):
        v = candidate.get(key)
        if v is True:
            return "EXPLICIT_REASSESSMENT"
        if isinstance(v, str) and v.upper() in REASSESSMENT_TRIGGERS:
            return v.upper()
    recon = candidate.get("reconciliation") or {}
    for code in recon.get("trigger_codes") or []:
        if str(code).upper() in REASSESSMENT_TRIGGERS:
            return str(code).upper()
    return None


def build_snapshot(candidate: dict[str, Any], cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    research_cfg = load_yaml_config(cfg, "research")
    snap_cfg = dict(research_cfg.get("snapshot") or {})
    rid = f"R{datetime.now(timezone.utc).strftime('%Y%m%d')}" + uuid4().hex[:6].upper()
    as_of = (
        candidate.get("as_of")
        or candidate.get("research_date")
        or (candidate.get("versions") or {}).get("as_of")
        or datetime.now(timezone.utc).date().isoformat()
    )
    if hasattr(as_of, "isoformat"):
        as_of = as_of.isoformat()
    as_of = str(as_of)[:10]
    from ashare.research.signal_contract import attach_signal_contract, serialize_signal_fields

    attach_signal_contract(candidate)
    sig_fields = serialize_signal_fields(candidate)
    rev_trigger = reassessment_trigger_of(candidate)
    store = SnapshotStore(cfg)
    rev = 1
    if rev_trigger:
        rev = store.next_revision(str(candidate.get("symbol") or ""), as_of)
    snap = {
        "research_id": rid,
        "snapshot_id": rid,
        "symbol": candidate.get("symbol"),
        "name": candidate.get("name"),
        "research_time": datetime.now(timezone.utc).isoformat(),
        "snapshot_time": datetime.now(timezone.utc).isoformat(),
        "research_date": as_of,
        "as_of": as_of,
        "revision": rev,
        "revision_trigger": rev_trigger or "INITIAL",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "versions": {
            "as_of": as_of,
            "factor_version": snap_cfg.get("factor_version") or candidate.get("factor_version") or "factor_v1",
            "news_version": ((candidate.get("news_package") or {}).get("versions") or {}).get("news_data_version")
            or snap_cfg.get("news_version")
            or "news_v1",
            "prompt_version": snap_cfg.get("prompt_bundle") or "prompts_v1",
            "prompt_bundle": snap_cfg.get("prompt_bundle") or "prompts_v1",
            "model_version": snap_cfg.get("model_bundle") or "models_v1",
            "model_bundle": snap_cfg.get("model_bundle") or "models_v1",
            "config_version": research_cfg.get("research_version") or "research_v1",
            "research_version": research_cfg.get("research_version") or "research_v1",
        },
        "trigger": candidate.get("trigger") or {},
        "quant": {
            "factor_score": candidate.get("candidate_score"),
            "leader_score": candidate.get("leader_score"),
            "ml_prediction": candidate.get("ml_prediction"),
            "ml_status": candidate.get("ml_status"),
            "ml_prediction_available": candidate.get("ml_prediction_available"),
            "momentum_score": candidate.get("score_momentum"),
            "relative_strength_score": candidate.get("score_relative_strength"),
            "value_score": candidate.get("score_value"),
            "quality_score": candidate.get("score_quality"),
            "liquidity_score": candidate.get("score_liquidity"),
            "breakout_score": candidate.get("score_breakout"),
            "factors": candidate.get("factors") or {},
            "board_count": candidate.get("board_count"),
            "chase_score": candidate.get("chase_score"),
        },
        "signals": candidate.get("signals") or sig_fields.get("signals") or {},
        "data_quality": candidate.get("data_quality") or sig_fields.get("data_quality"),
        "profit_score": sig_fields.get("profit_score", candidate.get("profit_score")),
        "profit_status": candidate.get("profit_status") or sig_fields.get("profit_score_status"),
        "event_score": sig_fields.get("event_score", candidate.get("event_score")),
        "event_status": candidate.get("event_status") or sig_fields.get("event_score_status"),
        "news_score": sig_fields.get("news_score", candidate.get("news_score")),
        "news_status": candidate.get("news_status") or sig_fields.get("news_score_status"),
        # serialize_signal_fields uses {name}_status; keep both for consumers
        "ml_prediction_status": sig_fields.get("ml_prediction_status"),
        "profit_score_status": sig_fields.get("profit_score_status"),
        "event_score_status": sig_fields.get("event_score_status"),
        "news_score_status": sig_fields.get("news_score_status"),
        "trade_timing_action": candidate.get("trade_timing_action"),
        "leader": {
            "lifecycle": candidate.get("lifecycle"),
            "stage": candidate.get("stage"),
            "chase_score": candidate.get("chase_score"),
            "trade_timing_score": candidate.get("trade_timing_score"),
            "trade_timing_action": candidate.get("trade_timing_action"),
            "board_count": candidate.get("board_count"),
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
        "priority_rank": candidate.get("priority_rank") or (candidate.get("gate") or {}).get("rank"),
        "research_eligibility": (candidate.get("gate") or {}).get("research_tier")
        or candidate.get("research_tier"),
    }
    snap["research_intelligence"] = build_research_intelligence(snap)
    return snap
