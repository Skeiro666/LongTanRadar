from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from ashare.config_loaders import load_yaml_config
from ashare.ml.ranking import MLRankingEngine
from ashare.research.council import AICouncilEngine, ChairmanEngine, DebateEngine
from ashare.research.gate import apply_research_gate
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
        prior = self.store.load_latest_for_symbol(str(candidate.get("symbol") or ""))
        snap = build_snapshot(candidate, self.cfg)
        opinions = self.council.run_parallel(
            snap,
            prior_snapshot=prior,
            prior_opinions=(prior or {}).get("council"),
        )
        council_meta = dict(opinions.get("_meta") or {})
        role_opinions = {k: v for k, v in opinions.items() if not k.startswith("_")}
        incremental_reused = sum(1 for v in role_opinions.values() if v.get("source") == "incremental_reuse")
        debate = self.debate.run(snap, role_opinions)
        from ashare.research.incremental import detect_change_reasons, roles_to_refresh, _incremental_cfg

        change_reasons = detect_change_reasons(snap, prior, self.cfg) if prior else ["MANUAL_REFRESH"]

        reuse_chair = (
            prior
            and _incremental_cfg(self.cfg).get("enabled", True)
            and not roles_to_refresh(snap, prior, self.cfg)
            and (prior.get("chairman") or {}).get("rating")
        )
        if reuse_chair:
            chairman = dict(prior["chairman"])
            chairman["source"] = "incremental_reuse"
        else:
            chairman = self.chair.summarize(snap, role_opinions, debate)
        report = {
            "research_id": snap["research_id"],
            "symbol": snap["symbol"],
            "name": snap.get("name"),
            "research_time": snap["research_time"],
            "research_tier": candidate.get("research_tier") or (candidate.get("gate") or {}).get("research_tier"),
            "trigger": snap.get("trigger"),
            "quant": snap.get("quant"),
            "profit_inflection": snap.get("profit_inflection"),
            "event": snap.get("event"),
            "council": opinions,
            "council_meta": council_meta,
            "debate": debate,
            "chairman": chairman,
            "change_reasons": change_reasons,
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
            "incremental_reused_roles": incremental_reused,
        }
        # persist full snapshot including AI outputs for replay
        full = {**snap, "council": opinions, "debate": debate, "chairman": chairman, "report": report}
        self.store.save(full)
        self._append_index(report)
        return report

    def run_pool(self, candidates: list[dict[str, Any]], panel: dict | None = None) -> list[dict[str, Any]]:
        ranked = list(candidates)
        if panel is not None:
            need_ml = any(r.get("ml_rank_score") is None for r in ranked)
            if need_ml:
                try:
                    from ashare.ml.candidate_ranking import apply_ml_rank_scores

                    ranked = self.ml.predict_rows(ranked)
                    ranked = apply_ml_rank_scores(ranked)
                except Exception:  # noqa: BLE001
                    pass

        max_n = int((self.research_cfg.get("funnel") or {}).get("max_council", 12))
        gate_batch = apply_research_gate(ranked, self.cfg)
        council_candidates = gate_batch.passed[:max_n]
        gate_cfg = dict((self.research_cfg.get("research_gate") or {}))
        max_llm = int(gate_cfg.get("max_llm_calls") or 30)
        llm_used = 0

        reports: list[dict[str, Any]] = []
        from ashare.research.progress import get_research_progress

        prog = get_research_progress()
        for i, c in enumerate(council_candidates):
            sym = str(c.get("symbol") or "")
            name = str(c.get("name") or sym)
            if llm_used >= max_llm:
                reports.append(self._budget_skip_report(c, llm_used))
                prog.log("council", f"跳过 {name} — LLM 预算用尽", level="warn")
                continue
            prog.log("council", f"[{i + 1}/{len(council_candidates)}] 研究 {name} ({sym})")
            rep = self.run_session(c)
            meta = dict((rep.get("council_meta") or {}))
            llm_used += len(meta.get("roles_called") or [])
            if (rep.get("chairman") or {}).get("source") not in {"incremental_reuse", "cache"}:
                llm_used += 1
            rating = (rep.get("decision") or {}).get("research_rating") or (rep.get("chairman") or {}).get("rating")
            prog.log("council", f"完成 {name} → {rating}", detail={"llm_used": llm_used})
            reports.append(rep)
        for c in gate_batch.rejected:
            reports.append(self._gate_skip_report(c))
        summary = gate_batch.summary()
        summary["llm_budget"] = {"max": max_llm, "used": llm_used}
        self._last_gate_summary = summary
        return reports

    def gate_summary(self) -> dict[str, Any]:
        return getattr(self, "_last_gate_summary", {})

    def _budget_skip_report(self, candidate: dict[str, Any], llm_used: int) -> dict[str, Any]:
        rep = self._gate_skip_report(candidate)
        rep["gate"] = {**(rep.get("gate") or {}), "reason": "LLM_BUDGET", "llm_used": llm_used}
        rep["chairman"]["rationale"] = "LLM_BUDGET"
        return rep

    def _gate_skip_report(self, candidate: dict[str, Any]) -> dict[str, Any]:
        gate = dict(candidate.get("gate") or {})
        rid = f"G{datetime.now(timezone.utc).strftime('%Y%m%d')}{uuid4().hex[:6].upper()}"
        reason = str(gate.get("reason") or "GATE_REJECT")
        return {
            "research_id": rid,
            "symbol": candidate.get("symbol"),
            "name": candidate.get("name"),
            "research_time": datetime.now(timezone.utc).isoformat(),
            "trigger": candidate.get("trigger"),
            "quant": {
                "leader_score": candidate.get("leader_score"),
                "ml_prediction": candidate.get("ml_prediction"),
                "factor_score": candidate.get("candidate_score"),
            },
            "profit_inflection": candidate.get("profit_inflection") or {},
            "event": candidate.get("event") or {},
            "gate": gate,
            "candidate_sources": candidate.get("candidate_sources") or [],
            "research_hypotheses": candidate.get("research_hypotheses") or [],
            "council": {},
            "debate": [],
            "chairman": {
                "source": "research_gate",
                "rating": "SKIP",
                "status": "skipped",
                "rationale": reason,
            },
            "decision": {
                "research_rating": "GATE_SKIP",
                "action": "NO_ACTION",
                "position_suggestion": 0,
            },
            "news_package": candidate.get("news_package") or {},
        }

    def _append_index(self, report: dict[str, Any]) -> None:
        root = Path(self.cfg.get("_root") or Path(__file__).resolve().parents[2])
        idx = root / "data" / "research_sessions.jsonl"
        idx.parent.mkdir(parents=True, exist_ok=True)
        with idx.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"research_id": report["research_id"], "symbol": report["symbol"], "rating": report["decision"]["research_rating"], "time": report["research_time"]}, ensure_ascii=False) + "\n")
