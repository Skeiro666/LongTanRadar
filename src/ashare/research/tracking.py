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
    ) -> dict[str, Any]:
        sym = to_symbol(report["symbol"])
        sources = list(report.get("candidate_sources") or [])
        base_meta = {
            "research_id": report.get("research_id"),
            "symbol": sym,
            "candidate_sources": sources,
            "discovery_sources": sources,
            "source_bucket": _source_bucket(sources),
            "rating": (report.get("chairman") or report.get("decision") or {}).get("rating")
            or (report.get("decision") or {}).get("research_rating"),
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
        has_bench = isinstance(benchmark_returns, dict) and bool(benchmark_returns)
        for h in self.horizons:
            if len(fut) < h:
                out_h[str(h)] = {"status": "pending"}
                continue
            px = float(fut.iloc[h - 1]["close"])
            ret = px / entry - 1.0
            # Do not pretend excess alpha when no real benchmark series
            if has_bench and str(h) in benchmark_returns:
                bench = float(benchmark_returns[str(h)])
                out_h[str(h)] = {
                    "actual_return": ret,
                    "benchmark_return": bench,
                    "excess_return": ret - bench,
                    "hit": ret > 0,
                }
            else:
                out_h[str(h)] = {
                    "actual_return": ret,
                    "benchmark_return": None,
                    "excess_return": None,
                    "hit": ret > 0,
                    "note": "no_benchmark_excess_unavailable",
                }
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
                "Excess uses equal-weight universe at research as_of when benchmark_wired=true",
            ],
        }

    def attribution_report(
        self,
        reports: list[dict[str, Any]],
        panel: dict[str, Any],
        *,
        horizon: str = "5",
        benchmark_returns: dict[str, float] | None = None,
        persist: bool = True,
    ) -> dict[str, Any]:
        outcomes = [
            self.tracking.outcomes_for_report(r, panel, benchmark_returns=benchmark_returns) for r in reports
        ]
        if persist and outcomes:
            self.persist_outcomes(outcomes)
        attr = self.summarize_by_source(outcomes, horizon=horizon)
        by_rating = self.summarize_by_rating(outcomes, horizon=horizon)
        ai_alpha = self.compute_ai_incremental_alpha(outcomes, horizon=horizon)
        return {
            "available": True,
            "outcomes": outcomes,
            "attribution": attr,
            "by_rating": by_rating,
            "ai_incremental_alpha": ai_alpha,
            "horizon": str(horizon),
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
        ab["note"] = "descriptive cohort compare; not OOS proof of AI alpha"
        return ab

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
