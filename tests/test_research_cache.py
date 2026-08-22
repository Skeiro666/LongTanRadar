from __future__ import annotations

from pathlib import Path

from ashare.research.cache import ResearchCache, compute_context_hash
from ashare.research.dynamic_council import select_council_roles, skipped_role_opinion


def _cfg(tmp_path: Path) -> dict:
    return {"_root": str(tmp_path)}


def test_context_hash_stable():
    ctx1 = {
        "symbol": "600000.SH",
        "quant_context": {"leader_score": 0.5},
        "factor_context": {"momentum_20d": 0.1},
    }
    ctx2 = {
        "symbol": "600000.SH",
        "quant_context": {"leader_score": 0.6},
        "factor_context": {"momentum_20d": 0.1},
    }
    h1 = compute_context_hash(
        symbol="600000.SH",
        role_id="quant",
        context=ctx1,
        prompt_version="quant_v1",
        model="m1",
    )
    h2 = compute_context_hash(
        symbol="600000.SH",
        role_id="quant",
        context=ctx1,
        prompt_version="quant_v1",
        model="m1",
    )
    assert h1 == h2
    h3 = compute_context_hash(
        symbol="600000.SH",
        role_id="quant",
        context=ctx2,
        prompt_version="quant_v1",
        model="m1",
    )
    assert h1 != h3


def test_research_cache_roundtrip(tmp_path: Path):
    cfg = {
        **_cfg(tmp_path),
        "research": {
            "research_cache": {"enabled": True, "dir": "data/cache/research", "ttl_hours": 24},
        },
    }
    cache = ResearchCache(cfg)
    key = "abc123"
    resp = {"role": "quant", "score": 0.5, "stance": "bull", "status": "ok"}
    cache.set(key, resp, {"symbol": "600000.SH"})
    got = cache.get(key)
    assert got == resp


def test_dynamic_council_skips_weak_quant(tmp_path: Path):
    cfg = {
        **_cfg(tmp_path),
        "research": {
            "dynamic_council": {
                "enabled": True,
                "min_leader_score": 0.5,
                "min_ml_prediction": 0.05,
            }
        },
    }
    snap = {
        "symbol": "600000.SH",
        "candidate_sources": [],
        "quant": {"leader_score": 0.05, "ml_prediction": 0.001},
        "profit_inflection": {"score": 0.0},
        "event": {"score": 0.0},
        "news_package": {"net_event_score": 0.0},
        "research_hypotheses": [],
        "value_available": False,
    }
    roles = select_council_roles(snap, cfg)
    assert "quant" not in roles
    assert "bear" in roles
    assert "valuation" not in roles


def test_dynamic_council_keeps_news_event(tmp_path: Path):
    cfg = {**_cfg(tmp_path), "research": {"dynamic_council": {"enabled": True}}}
    snap = {
        "candidate_sources": ["news"],
        "quant": {"leader_score": 0.0},
        "profit_inflection": {},
        "event": {"score": 0.0},
        "news_package": {"net_event_score": 0.3},
        "research_hypotheses": [{"type": "HYPOTHESIS"}],
        "value_available": False,
    }
    roles = select_council_roles(snap, cfg)
    assert "event" in roles
    assert "bear" in roles


def test_skipped_role_opinion_shape():
    op = skipped_role_opinion("quant", "test")
    assert op["status"] == "skipped"
    assert op["source"] == "dynamic_council"
