from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ashare.config_loaders import load_yaml_config
from ashare.ml.ranking import MLRankingEngine
from ashare.research.council import AICouncilEngine, ChairmanEngine, DebateEngine
from ashare.research.snapshot import SnapshotStore, build_snapshot
from ashare.symbols import to_symbol


class ResearchSessionEngine:
    """Orchestrate candidate → snapshot → council → debate → chairman → report."""

    def __init__(self, cfg: dict[str, Any] | None = None) -> None:
        self.cfg = cfg or {}
        self.research_cfg = load_yaml_config(self.cfg, "research")
        self.council = AICouncilEngine(self.cfg)
        self.debate = DebateEngine(self.cfg)
        self.chair = ChairmanEngine(self.cfg)
        self.store = SnapshotStore(self.cfg)
        self.ml = MLRankingEngine(self.cfg)

    def run_session(self, candidate: dict[str, Any]) -> dict[str, Any]:
        snap = build_snapshot(candidate, self.cfg)
        opinions = self.council.run_parallel(snap)
        debate = self.debate.run(snap, opinions)
        chairman = self.chair.summarize(snap, opinions, debate)
        report = {
            "research_id": snap["research_id"],
            "symbol": snap["symbol"],
            "name": snap.get("name"),
            "research_time": snap["research_time"],
            "trigger": snap.get("trigger"),
            "quant": snap.get("quant"),
            "profit_inflection": snap.get("profit_inflection"),
            "event": snap.get("event"),
            "council": opinions,
            "debate": debate,
            "chairman": chairman,
            "decision": {
                "research_rating": chairman.get("rating"),
                "action": chairman.get("trading_action"),
                "position_suggestion": chairman.get("position_suggestion") or 0,
            },
            "versions": snap.get("versions"),
            "snapshot": {
                "market": snap.get("market"),
                "value_available": snap.get("value_available"),
                "market_regime": snap.get("market_regime"),
            },
            "news_package": snap.get("news_package") or {},
            "news_snapshot": snap.get("news_snapshot") or {},
            "candidate_sources": snap.get("candidate_sources") or [],
            "research_hypotheses": snap.get("research_hypotheses") or [],
            "research_intelligence": snap.get("research_intelligence") or {},
        }
        # persist full snapshot including AI outputs for replay
        full = {**snap, "council": opinions, "debate": debate, "chairman": chairman, "report": report}
        self.store.save(full)
        self._append_index(report)
        return report

    def run_pool(self, candidates: list[dict[str, Any]], panel: dict | None = None) -> list[dict[str, Any]]:
        ranked = list(candidates)
        if panel is not None:
            try:
                # ensure factors present; ML optional
                ranked = self.ml.predict_rows(ranked)
            except Exception:  # noqa: BLE001
                pass
        max_n = int((self.research_cfg.get("funnel") or {}).get("max_council", 12))
        reports = []
        for c in ranked[:max_n]:
            reports.append(self.run_session(c))
        return reports

    def _append_index(self, report: dict[str, Any]) -> None:
        root = Path(self.cfg.get("_root") or Path(__file__).resolve().parents[2])
        idx = root / "data" / "research_sessions.jsonl"
        idx.parent.mkdir(parents=True, exist_ok=True)
        with idx.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"research_id": report["research_id"], "symbol": report["symbol"], "rating": report["decision"]["research_rating"], "time": report["research_time"]}, ensure_ascii=False) + "\n")
