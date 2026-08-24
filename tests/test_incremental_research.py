"""V5 Phase 4/7 â€?cache key + incremental change_reason tests."""

from __future__ import annotations

from ashare.research.cache import compute_candidate_hash, compute_context_hash, extract_version_meta
from ashare.research.incremental import detect_change_reasons, roles_to_refresh


def test_candidate_hash_changes_with_score():
    h1 = compute_candidate_hash({"candidate_score": 0.5, "candidate_sources": ["quant"]})
    h2 = compute_candidate_hash({"candidate_score": 0.6, "candidate_sources": ["quant"]})
    assert h1 != h2


def test_context_hash_includes_versions():
    base = {
        "symbol": "600000.SH",
        "role_id": "quant",
        "context": {"x": 1},
        "prompt_version": "quant_v1",
        "model": "m",
        "factor_version": "factor_v1",
        "news_version": "news_v1",
        "model_version": "models_v1",
        "as_of": "2024-06-10",
        "candidate_hash": "abc",
    }
    h1 = compute_context_hash(**base)
    h2 = compute_context_hash(**{**base, "news_version": "news_v2"})
    assert h1 != h2


def test_extract_version_meta_from_snapshot():
    snap = {
        "versions": {"factor_version": "factor_v1", "model_bundle": "models_v1"},
        "news_snapshot": {"news_data_version": "news_v2"},
        "snapshot_time": "2024-06-10T12:00:00+00:00",
        "quant": {"factor_score": 0.4, "leader_score": 0.3},
        "candidate_sources": ["quant"],
    }
    meta = extract_version_meta(snap)
    assert meta["news_version"] == "news_v2"
    assert meta["as_of"].startswith("2024-06-10")
    assert meta["candidate_hash"]


def test_detect_change_reasons_no_change():
    snap = {
        "versions": {"factor_version": "f1", "model_bundle": "m1"},
        "news_snapshot": {"news_data_version": "n1", "event_ids": ["E1"]},
        "market": {"pct_chg": 1.0},
        "price_in_risk": "LOW",
        "quant": {"factor_score": 0.4, "leader_score": 0.2},
        "candidate_sources": ["quant"],
        "symbol": "600000.SH",
    }
    reasons = detect_change_reasons(snap, dict(snap))
    assert reasons == ["NO_CHANGE"]


def test_detect_change_reasons_new_event():
    prior = {
        "versions": {"factor_version": "f1", "model_bundle": "m1"},
        "news_snapshot": {"news_data_version": "n1", "event_ids": ["E1"]},
        "market": {"pct_chg": 1.0},
        "price_in_risk": "LOW",
        "quant": {"factor_score": 0.4},
        "candidate_sources": ["quant"],
        "symbol": "600000.SH",
    }
    cur = {**prior, "news_snapshot": {"news_data_version": "n1", "event_ids": ["E1", "E2"]}}
    reasons = detect_change_reasons(cur, prior)
    assert "NEW_EVENT" in reasons


def test_roles_to_refresh_no_change_returns_empty():
    cfg = {"_root": ".", "research": {"incremental_research": {"enabled": True}, "dynamic_council": {"enabled": True}}}
    snap = {
        "symbol": "600000.SH",
        "candidate_sources": ["quant"],
        "quant": {"leader_score": 0.5, "ml_prediction": 0.01},
        "profit_inflection": {"score": 0.0},
        "event": {"score": 0.0},
        "news_package": {"net_event_score": 0.0},
        "research_hypotheses": [],
        "value_available": False,
        "versions": {"factor_version": "f1", "model_bundle": "m1"},
        "news_snapshot": {"news_data_version": "n1", "event_ids": []},
        "market": {"pct_chg": 0.0},
        "price_in_risk": "LOW",
    }
    assert roles_to_refresh(snap, dict(snap), cfg) == ()
