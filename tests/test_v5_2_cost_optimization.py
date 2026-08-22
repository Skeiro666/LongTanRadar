"""V5.2 Phase 3 — role-specific cache hash + chairman slim context."""

from __future__ import annotations

from ashare.research.cache import compute_context_hash, project_context_for_hash
from ashare.research.intel_package import build_chairman_context, build_role_context
from tests.test_role_context import _cfg, _sample_snapshot


def test_project_context_for_hash_quant_ignores_unrelated_news_fields():
    ctx = {
        "symbol": "600000.SH",
        "quant_context": {"leader_score": 0.5},
        "factor_context": {"momentum_20d": 0.1},
        "risk_context": {"market_regime": "RISK_ON"},
        "news_context": {"counts": {"last_7d": 3}},
        "evidence_ids": ["N1", "N2"],
        "extra_news_only": {"timeline": [{"title": "changed"}]},
    }
    proj = project_context_for_hash("quant", ctx)
    assert "extra_news_only" not in proj
    assert "evidence_ids" not in proj
    assert proj["quant_context"]["leader_score"] == 0.5


def test_quant_hash_stable_when_unrelated_news_changes():
    snap = _sample_snapshot()
    base_ctx = build_role_context(snap, "quant", cfg=_cfg())
    meta = {
        "symbol": "000786.SZ",
        "role_id": "quant",
        "prompt_version": "quant_v1",
        "model": "m",
        "factor_version": "factor_v1",
        "news_version": "news_v1",
        "model_version": "models_v1",
        "as_of": "2026-08-20",
        "candidate_hash": "abc",
    }
    h1 = compute_context_hash(context=base_ctx, **meta)
    noisy = dict(base_ctx)
    noisy["extra_news_only"] = {"last_7d": [{"title": "noise"}]}
    h2 = compute_context_hash(context=noisy, **meta)
    assert h1 == h2


def test_chairman_payload_role_reports_only():
    snap = _sample_snapshot()
    opinions = {"quant": {"role": "quant", "score": 0.2, "stance": "bull", "status": "ok"}}
    payload = build_chairman_context(snap, opinions, [], cfg=_cfg())
    assert set(payload.keys()) >= {"role_reports", "evidence_ids", "rules"}
    assert "research_intelligence" not in payload
    assert "quant" in payload["role_reports"]
