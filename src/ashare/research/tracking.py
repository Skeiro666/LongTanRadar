from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from ashare.config_loaders import load_yaml_config
from ashare.symbols import to_symbol


def _source_bucket(sources: list[str] | None) -> str:
    srcs = sorted({str(s).lower() for s in (sources or []) if s})
    if not srcs:
        return "unknown"
    has_news = "news" in srcs
    non_news = [s for s in srcs if s != "news"]
    if has_news and not non_news:
        return "news_only"
    if has_news and non_news:
        return "news_plus_quant"
    return "quant_only"


class TrackingEngine:
    """Attach realized returns at horizons after research_time."""

    def __init__(self, cfg: dict[str, Any] | None = None) -> None:
        self.cfg = cfg or {}
        self.horizons = list(
            (load_yaml_config(self.cfg, "research").get("tracking") or {}).get("horizons_days")
            or [1, 3, 5, 10, 20, 60]
        )

    def outcomes_for_report(
        self,
        report: dict[str, Any],
        panel: dict[str, pd.DataFrame],
        benchmark_returns: dict[str, float] | None = None,
        *,
        market_benchmark_returns: dict[str, float] | None = None,
        universe_benchmark_returns: dict[str, float] | None = None,
    ) -> dict[str, Any]:
        sym = to_symbol(report["symbol"])
        sources = list(report.get("candidate_sources") or [])
        base_meta = {
            "research_id": report.get("research_id"),
            "snapshot_id": report.get("research_id"),
            "decision_id": report.get("research_id"),
            "symbol": sym,
            "candidate_sources": sources,
            "discovery_sources": sources,
            "source_bucket": _source_bucket(sources),
            "rating": (report.get("chairman") or report.get("decision") or {}).get("rating")
            or (report.get("decision") or {}).get("research_rating"),
            "signal_time": report.get("research_time") or report.get("as_of"),
        }
        df = panel.get(sym)
        if df is None or df.empty:
            return {**base_meta, "status": "no_bars", "horizons": {}}
        df = df.copy()
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date")
        as_of = pd.Timestamp(str(report.get("research_time") or report.get("as_of"))[:10])
        hist = df[df["date"] <= as_of]
        if hist.empty:
            return {**base_meta, "status": "no_asof", "horizons": {}}
        entry = float(hist.iloc[-1]["close"])
        fut = df[df["date"] > as_of]
        out_h: dict[str, Any] = {}
        mkt_map = market_benchmark_returns if market_benchmark_returns is not None else benchmark_returns
        uni_map = universe_benchmark_returns
        for h in self.horizons:
            if len(fut) < h:
                out_h[str(h)] = {"status": "pending"}
                continue
            px = float(fut.iloc[h - 1]["close"])
            ret = px / entry - 1.0
            h_key = str(h)
            mkt_b = float(mkt_map[h_key]) if isinstance(mkt_map, dict) and h_key in mkt_map else None
            uni_b = float(uni_map[h_key]) if isinstance(uni_map, dict) and h_key in uni_map else None
            primary_bench = mkt_b if mkt_b is not None else uni_b
            cell: dict[str, Any] = {
                "actual_return": ret,
                "total_return": ret,
                "market_benchmark_return": mkt_b,
                "universe_benchmark_return": uni_b,
                "market_alpha": (ret - mkt_b) if mkt_b is not None else None,
                "selection_alpha": (ret - uni_b) if uni_b is not None else None,
                "benchmark_return": primary_bench,
                "excess_return": (ret - primary_bench) if primary_bench is not None else None,
                "hit": ret > 0,
            }
            if primary_bench is None:
                cell["note"] = "no_benchmark_excess_unavailable"
            out_h[h_key] = cell
        return {**base_meta, "horizons": out_h, "status": "ok"}


class ReviewEngine:
    """Aggregate rating / discovery-source → outcome stats. No fabricated alpha."""

    def __init__(self, cfg: dict[str, Any] | None = None) -> None:
        self.cfg = cfg or {}
        self.tracking = TrackingEngine(cfg)

    def summarize_by_rating(self, outcomes: list[dict[str, Any]], horizon: str = "5") -> dict[str, Any]:
        buckets: dict[str, list[float]] = {}
        for o in outcomes:
            rating = str(o.get("rating") or "UNKNOWN")
            cell = (o.get("horizons") or {}).get(horizon) or {}
            if "actual_return" not in cell:
                continue
            buckets.setdefault(rating, []).append(float(cell["actual_return"]))
        stats = {}
        for rating, rets in buckets.items():
            s = pd.Series(rets)
            stats[rating] = {
                "n": int(len(rets)),
                "mean_return": float(s.mean()),
                "median_return": float(s.median()),
                "win_rate": float((s > 0).mean()),
            }
        return {"horizon": horizon, "by_rating": stats}

    def summarize_by_source(self, outcomes: list[dict[str, Any]], horizon: str = "5") -> dict[str, Any]:
        """Group by source_bucket and by individual discovery tags."""
        by_bucket: dict[str, list[float]] = {}
        by_tag: dict[str, list[float]] = {}
        by_bucket_ex: dict[str, list[float]] = {}
        by_tag_ex: dict[str, list[float]] = {}
        pending = 0
        for o in outcomes:
            cell = (o.get("horizons") or {}).get(str(horizon)) or {}
            if "actual_return" not in cell:
                pending += 1
                continue
            ret = float(cell["actual_return"])
            bucket = str(o.get("source_bucket") or _source_bucket(o.get("candidate_sources")))
            by_bucket.setdefault(bucket, []).append(ret)
            tags = o.get("candidate_sources") or o.get("discovery_sources") or []
            if not tags:
                by_tag.setdefault("unknown", []).append(ret)
            for t in tags:
                by_tag.setdefault(str(t), []).append(ret)
            ex = cell.get("selection_alpha")
            if ex is None:
                ex = cell.get("market_alpha")
            if ex is None:
                ex = cell.get("excess_return")
            if ex is not None:
                by_bucket_ex.setdefault(bucket, []).append(float(ex))
                tag_list = tags or ["unknown"]
                for t in tag_list:
                    by_tag_ex.setdefault(str(t), []).append(float(ex))

        def _stats(rets: list[float], excess: list[float] | None = None) -> dict[str, Any]:
            s = pd.Series(rets)
            out: dict[str, Any] = {
                "n": int(len(rets)),
                "mean_return": float(s.mean()),
                "median_return": float(s.median()),
                "win_rate": float((s > 0).mean()),
            }
            if excess:
                ex = pd.Series(excess)
                out["mean_excess_return"] = float(ex.mean())
                out["excess_available"] = True
            else:
                out["excess_available"] = False
                out["note"] = "stock return only; excess requires real benchmark"
            return out

        has_excess = bool(by_bucket_ex)
        return {
            "horizon": str(horizon),
            "n_outcomes": len(outcomes),
            "n_pending_or_missing": pending,
            "by_source_bucket": {
                k: _stats(v, by_bucket_ex.get(k)) for k, v in sorted(by_bucket.items())
            },
            "by_discovery_source": {
                k: _stats(v, by_tag_ex.get(k)) for k, v in sorted(by_tag.items())
            },
            "benchmark_wired": has_excess,
            "rules": [
                "Attribution is descriptive only — does not change trading weights",
                "News ≠ BUY; source win-rate is not an auto-trade signal",
                "market_alpha = stock - CSI300; selection_alpha = stock - equal-weight universe",
            ],
        }

    def attribution_report(
        self,
        reports: list[dict[str, Any]],
        panel: dict[str, Any],
        *,
        horizon: str = "5",
        benchmark_returns: dict[str, float] | None = None,
        market_benchmark_returns: dict[str, float] | None = None,
        universe_benchmark_returns: dict[str, float] | None = None,
        benchmark_snapshot: dict[str, Any] | None = None,
        persist: bool = True,
    ) -> dict[str, Any]:
        mkt = market_benchmark_returns if market_benchmark_returns is not None else benchmark_returns
        uni = universe_benchmark_returns
        outcomes = [
            self.tracking.outcomes_for_report(
                r,
                panel,
                benchmark_returns=benchmark_returns,
                market_benchmark_returns=mkt,
                universe_benchmark_returns=uni,
            )
            for r in reports
        ]
        tracking_cfg = dict(load_yaml_config(self.cfg, "research").get("tracking") or {})
        if tracking_cfg.get("execution_tracking", True) and outcomes:
            from ashare.research.execution_tracking import attach_paper_execution, load_paper_fills

            syms = [str(r.get("symbol") or "") for r in reports]
            fills_by_sym = load_paper_fills(self.cfg, symbols=syms)
            report_by_sym = {str(r.get("symbol")): r for r in reports}
            for o in outcomes:
                rep = report_by_sym.get(str(o.get("symbol"))) or {}
                attach_paper_execution(o, rep, fills_by_sym, panel=panel)
        from ashare.research.outcome_truth import apply_primary_truth, summarize_portfolio_attribution

        outcomes = apply_primary_truth(outcomes)
        if persist and outcomes:
            self.persist_outcomes(outcomes)
        portfolio_truth = summarize_portfolio_attribution(outcomes, horizon=str(horizon))
        attr = self.summarize_by_source(outcomes, horizon=horizon)
        by_rating = self.summarize_by_rating(outcomes, horizon=horizon)
        legacy_alpha = self.compute_ai_incremental_alpha(outcomes, horizon=horizon)
        topk_alpha = self.compute_topk_ablation_alpha(reports, outcomes, horizon=horizon)
        discovery_attr = self.summarize_discovery_sources(outcomes, horizon=horizon)
        # V5.2 P2-1: canonical ai_incremental_alpha = same-universe Top-K ablation
        unified_alpha = dict(topk_alpha)
        unified_alpha["canonical"] = True
        if unified_alpha.get("available"):
            unified_alpha["note"] = (
                topk_alpha.get("note") or "Same-universe Top-K ablation (canonical V5.2 metric)"
            )
        return {
            "available": True,
            "outcomes": outcomes,
            "attribution": attr,
            "by_rating": by_rating,
            "ai_incremental_alpha": unified_alpha,
            "ai_topk_ablation": topk_alpha,
            "ai_incremental_alpha_legacy": legacy_alpha,
            "discovery_attribution": discovery_attr,
            "horizon": str(horizon),
            "benchmark_snapshot": benchmark_snapshot,
            "portfolio_attribution": portfolio_truth,
            "outcome_truth": {
                "primary_source_rule": "paper_fill > signal_close",
                "note": "Per-symbol alpha uses primary_horizons; account PnL remains paper broker equity.",
            },
        }

    def compute_topk_ablation_alpha(
        self,
        reports: list[dict[str, Any]],
        outcomes: list[dict[str, Any]],
        *,
        horizon: str = "5",
        top_k: int = 5,
    ) -> dict[str, Any]:
        """
        V5 AI Incremental Alpha: same universe, same as_of rules — only variable is ranking.
        Baseline Top-K by candidate_score vs AI Top-K by council rating/confidence.
        """
        outcome_by_sym = {str(o.get("symbol")): o for o in outcomes}

        def _return(sym: str) -> float | None:
            cell = (outcome_by_sym.get(sym) or {}).get("horizons") or {}
            c = cell.get(str(horizon)) or {}
            if c.get("selection_alpha") is not None:
                return float(c["selection_alpha"])
            if c.get("market_alpha") is not None:
                return float(c["market_alpha"])
            if c.get("excess_return") is not None:
                return float(c["excess_return"])
            if c.get("actual_return") is not None:
                return float(c["actual_return"])
            return None

        eligible: list[dict[str, Any]] = []
        for r in reports:
            rating = str((r.get("decision") or {}).get("research_rating") or (r.get("chairman") or {}).get("rating") or "")
            if rating in {"GATE_SKIP", "SKIP"}:
                continue
            sym = str(r.get("symbol") or "")
            if _return(sym) is None:
                continue
            eligible.append(r)

        if len(eligible) < 2:
            return {
                "available": False,
                "insufficient_sample": True,
                "sample_count": len(eligible),
                "note": "need >=2 symbols with realized horizon returns",
            }

        def baseline_score(r: dict[str, Any]) -> float:
            q = r.get("quant") or {}
            return float(q.get("factor_score") or q.get("leader_score") or r.get("candidate_score") or 0)

        def ai_score(r: dict[str, Any]) -> float:
            rating = str((r.get("decision") or {}).get("research_rating") or (r.get("chairman") or {}).get("rating") or "WATCH")
            weights = {"STRONG_BUY": 3.0, "BUY": 2.0, "WATCH": 1.0, "PASS": 0.0, "SELL": -1.0}
            conf = float((r.get("chairman") or {}).get("confidence") or 0)
            return weights.get(rating, 0.5) + conf

        k = min(top_k, len(eligible))
        baseline_top = sorted(eligible, key=baseline_score, reverse=True)[:k]
        ai_top = sorted(eligible, key=ai_score, reverse=True)[:k]

        def _mean(reps: list[dict[str, Any]]) -> dict[str, Any]:
            rets = [_return(str(r["symbol"])) for r in reps]
            rets = [x for x in rets if x is not None]
            if not rets:
                return {"n": 0, "mean_return": None, "hit_rate": None}
            s = pd.Series(rets)
            return {"n": len(rets), "mean_return": float(s.mean()), "hit_rate": float((s > 0).mean())}

        bm = _mean(baseline_top)
        am = _mean(ai_top)
        incremental = None
        if bm.get("mean_return") is not None and am.get("mean_return") is not None:
            incremental = float(am["mean_return"]) - float(bm["mean_return"])

        use_excess = any(
            ((outcome_by_sym.get(str(r["symbol"])) or {}).get("horizons") or {}).get(str(horizon), {}).get("excess_return")
            is not None
            for r in eligible
        )

        return {
            "available": True,
            "insufficient_sample": k < 2,
            "method": "same_universe_topk_ablation",
            "ranking_method": "heuristic_rating_to_score",
            "horizon": str(horizon),
            "top_k": k,
            "sample_count": len(eligible),
            "metric": "mean_excess_return" if use_excess else "mean_return",
            "baseline_topk": {
                "symbols": [r.get("symbol") for r in baseline_top],
                **bm,
            },
            "ai_topk": {
                "symbols": [r.get("symbol") for r in ai_top],
                **am,
            },
            "ai_incremental_alpha": incremental,
            "note": "Same candidate universe; only ranking differs (score vs council rating)",
        }

    def compute_ai_incremental_alpha(
        self,
        outcomes: list[dict[str, Any]],
        *,
        horizon: str = "5",
    ) -> dict[str, Any]:
        """
        Descriptive compare: quant-only discovery bucket vs council-reviewed (non GATE_SKIP).
        Uses excess_return when benchmark wired; else actual_return with note.
        """
        quant_rets: list[float] = []
        council_rets: list[float] = []
        use_excess = False
        for o in outcomes:
            rating = str(o.get("rating") or "")
            if rating in {"GATE_SKIP", "SKIP"}:
                continue
            cell = (o.get("horizons") or {}).get(str(horizon)) or {}
            val = cell.get("excess_return")
            if val is not None:
                use_excess = True
            else:
                val = cell.get("actual_return")
            if val is None:
                continue
            ret = float(val)
            bucket = str(o.get("source_bucket") or _source_bucket(o.get("candidate_sources")))
            if bucket == "quant_only":
                quant_rets.append(ret)
            else:
                council_rets.append(ret)

        def _pack(rets: list[float]) -> dict[str, float]:
            if not rets:
                return {"n": 0.0, "mean_return": 0.0, "win_rate": 0.0}
            s = pd.Series(rets)
            return {
                "n": float(len(rets)),
                "mean_return": float(s.mean()),
                "win_rate": float((s > 0).mean()),
            }

        qm = _pack(quant_rets)
        cm = _pack(council_rets)
        metric_key = "mean_excess" if use_excess else "mean_return"
        ab = self.ab_compare(
            {metric_key: qm["mean_return"], "win_rate": qm["win_rate"], "n": qm["n"]},
            {metric_key: cm["mean_return"], "win_rate": cm["win_rate"], "n": cm["n"]},
        )
        ab["horizon"] = str(horizon)
        ab["metric"] = metric_key
        ab["quant_only_bucket"] = qm
        ab["council_reviewed_bucket"] = cm
        ab["note"] = "legacy cohort compare; see ai_topk_ablation for same-universe Top-K"
        return ab

    def summarize_discovery_sources(self, outcomes: list[dict[str, Any]], horizon: str = "5") -> dict[str, Any]:
        """Per discovery tag (quant/news/event/profit/ml) excess return stats."""
        tags = ("quant", "news", "event", "profit", "ml")
        by_tag: dict[str, list[float]] = {t: [] for t in tags}
        for o in outcomes:
            cell = (o.get("horizons") or {}).get(str(horizon)) or {}
            val = cell.get("excess_return")
            if val is None:
                val = cell.get("actual_return")
            if val is None:
                continue
            srcs = set(str(s).lower() for s in (o.get("candidate_sources") or []))
            for t in tags:
                if t in srcs:
                    by_tag[t].append(float(val))
        out: dict[str, Any] = {"horizon": str(horizon), "sources": {}}
        for t, rets in by_tag.items():
            if not rets:
                out["sources"][t] = {"n": 0, "mean_return": None, "insufficient_sample": True}
            else:
                s = pd.Series(rets)
                out["sources"][t] = {
                    "n": len(rets),
                    "mean_return": float(s.mean()),
                    "hit_rate": float((s > 0).mean()),
                    "insufficient_sample": len(rets) < 3,
                }
        return out

    def ab_compare(self, quant_only: dict[str, float], quant_ai: dict[str, float]) -> dict[str, Any]:
        """Caller supplies metric dicts (CAGR/Sharpe/...). No fabrication."""
        keys = sorted(set(quant_only) | set(quant_ai))
        delta = {k: float(quant_ai.get(k, 0) - quant_only.get(k, 0)) for k in keys}
        improved = sum(1 for k, v in delta.items() if v > 0)
        return {
            "quant_only": quant_only,
            "quant_plus_ai": quant_ai,
            "delta": delta,
            "ai_helped_metrics": improved,
            "conclusion": "inconclusive_until_oos"
            if not keys
            else ("ai_positive" if improved > len(keys) / 2 else "ai_not_helping"),
        }

    def persist_outcomes(self, outcomes: list[dict[str, Any]]) -> Path:
        root = Path(self.cfg.get("_root") or Path(__file__).resolve().parents[2])
        path = root / "data" / "research_outcomes.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(outcomes, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        return path

    def load_outcomes(self) -> list[dict[str, Any]]:
        root = Path(self.cfg.get("_root") or Path(__file__).resolve().parents[2])
        path = root / "data" / "research_outcomes.json"
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except Exception:  # noqa: BLE001
            return []
