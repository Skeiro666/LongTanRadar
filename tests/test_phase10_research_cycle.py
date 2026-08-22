"""Phase 10 — offline research-cycle contract (no live broker, no network providers)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from ashare.candidate import CandidateEngine
from ashare.news.models import RawNews, make_id, title_hash
from ashare.news.opportunity import NewsOpportunityEngine
from ashare.research.session import ResearchSessionEngine
from ashare.research.tracking import ReviewEngine
from tests.test_platform_engines import _synth_bars


def _news(title: str) -> RawNews:
    return RawNews(
        id=make_id("N"),
        source="sina",
        title=title,
        fetched_at=datetime.now(timezone.utc).isoformat(),
        summary=title,
        published_at="2024-06-10 10:00:00",
        title_hash=title_hash(title),
        media="fixture",
    )


def test_phase10_research_cycle_offline(monkeypatch, tmp_path):
    """
    Simulate one research cycle:
    discovery → union → council session → outcomes/attribution.
    Never places orders; never requires LLM key.
    """
    root = Path(__file__).resolve().parents[1]
    cfg = {
        "_root": str(tmp_path),
        "research": {
            "enabled": True,
            "funnel": {"max_research_pool": 5, "max_council": 3, "max_union_candidates": 20},
            "tracking": {"horizons_days": [1, 3, 5], "attribution_horizon": 5},
        },
    }
    # copy minimal yaml loads via root — point _root to project for yaml, persist under tmp
    cfg_yaml = {"_root": str(root), **{k: v for k, v in cfg.items() if k != "_root"}}
    cfg_yaml["_root"] = str(root)

    a, b = "600000.SH", "000786.SZ"
    da, db = _synth_bars(seed=1), _synth_bars(seed=2)
    # stretch history so as_of can leave future bars for outcomes
    for df, sym in ((da, a), (db, b)):
        df["symbol"] = sym
        df["date"] = pd.bdate_range("2024-01-02", periods=len(df))
    panel = {a: da, b: db}

    disc = NewsOpportunityEngine(cfg_yaml).discover(
        persist=False,
        news=[_news(f"{b[:6]}签订重大合同订单金额10亿")],
        name_map={b: "北新建材"},
    )
    assert disc["available"] is True
    assert any(c["symbol"] == b for c in disc["news_candidates"])
    for c in disc["news_candidates"]:
        assert "BUY" not in str(c.get("status", "")).upper()

    monkeypatch.setattr(
        "ashare.news.engine.NewsIntelligenceEngine.collect_stock",
        lambda self, symbol, **kw: {
            "net_event_score": 0.2,
            "news_data_incomplete": False,
            "news_ids": ["Nfix"],
            "expectation": {"available": False},
            "counts": {"last_7d": 1},
        },
    )
    # Heuristic council (no LLM)
    monkeypatch.setattr(
        "ashare.research.council.AICouncilEngine.run_parallel",
        lambda self, snap: [
            {
                "role_id": "quant",
                "stance": "WATCH",
                "confidence": 0.5,
                "points": ["fixture"],
                "challenges": [],
                "falsify": "",
            }
        ],
    )
    monkeypatch.setattr(
        "ashare.research.council.DebateEngine.run",
        lambda self, snap, opinions: [],
    )
    monkeypatch.setattr(
        "ashare.research.council.ChairmanEngine.summarize",
        lambda self, snap, opinions, debate: {
            "rating": "WATCH",
            "trading_action": "WAIT_FOR_CONFIRMATION",
            "confidence": 0.4,
            "base_case": "fixture cycle",
            "risks": ["news≠buy"],
            "position_suggestion": 0,
            "time_horizon": "T+1",
        },
    )
    monkeypatch.setattr(
        "ashare.ml.ranking.MLRankingEngine.predict_rows",
        lambda self, rows: rows,
    )

    uni = CandidateEngine(cfg_yaml).build_research_universe(
        panel,
        pool={
            "candidates": [
                {
                    "symbol": a,
                    "name": "浦发银行",
                    "source": "tech_leader",
                    "sources": ["tech_leader"],
                    "event_tags": ["技术龙头"],
                    "thesis": "tech",
                }
            ],
            "sources": {"tech_leader": 1},
        },
        news_discovery=disc,
    )
    assert uni["n_union"] >= 1
    assert any("news" in (r.get("candidate_sources") or []) for r in uni["research_universe"])

    # Force research_time into mid-panel so 5d outcomes resolve
    mid = str(pd.to_datetime(da["date"].iloc[len(da) // 3]).date())

    def _snap(candidate, cfg=None):
        from ashare.research.snapshot import build_snapshot as real

        s = real(candidate, cfg)
        s["research_time"] = mid + "T00:00:00+00:00"
        return s

    monkeypatch.setattr("ashare.research.session.build_snapshot", _snap)

    reports = ResearchSessionEngine(cfg_yaml).run_pool(uni["research_universe"], panel=panel)
    assert reports
    for r in reports:
        assert r.get("decision", {}).get("action") != "BUY"
        # news alone must not become SMALL_POSITION in this fixture chair
        assert r.get("decision", {}).get("research_rating") == "WATCH"

    pack = ReviewEngine(cfg_yaml).attribution_report(reports, panel, horizon="5", persist=False)
    assert pack["available"] is True
    assert pack["attribution"]["by_source_bucket"]
    # descriptive only
    assert "trading_action" not in pack
    assert all(
        (o.get("horizons") or {}).get("5", {}).get("excess_return") is None
        or isinstance((o.get("horizons") or {}).get("5", {}).get("excess_return"), float)
        for o in pack["outcomes"]
        if o.get("status") == "ok"
    )
