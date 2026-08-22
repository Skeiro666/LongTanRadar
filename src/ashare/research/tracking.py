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

        def _stats(rets: list[float]) -> dict[str, Any]:
            s = pd.Series(rets)
            return {
                "n": int(len(rets)),
                "mean_return": float(s.mean()),
                "median_return": float(s.median()),
                "win_rate": float((s > 0).mean()),
                "excess_available": False,
                "note": "stock return only; excess requires real benchmark",
            }

        return {
            "horizon": str(horizon),
            "n_outcomes": len(outcomes),
            "n_pending_or_missing": pending,
            "by_source_bucket": {k: _stats(v) for k, v in sorted(by_bucket.items())},
            "by_discovery_source": {k: _stats(v) for k, v in sorted(by_tag.items())},
            "rules": [
                "Attribution is descriptive only — does not change trading weights",
                "News ≠ BUY; source win-rate is not an auto-trade signal",
                "Do not treat mean_return as alpha without a real benchmark",
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
        return {
            "available": True,
            "outcomes": outcomes,
            "attribution": attr,
            "by_rating": by_rating,
            "horizon": str(horizon),
        }

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
