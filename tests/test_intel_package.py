from __future__ import annotations

from ashare.config_loaders import load_yaml_config
from ashare.research.council import AICouncilEngine
from ashare.research.intel_package import build_research_intelligence
from ashare.research.snapshot import build_snapshot


def test_prompts_event_v1_is_top_level_key():
    root = __file__.replace("\\", "/")
    # load via config helper
    from pathlib import Path

    cfg = {"_root": str(Path(__file__).resolve().parents[1])}
    prompts = load_yaml_config(cfg, "prompts")
    roles = prompts.get("roles") or {}
    assert "event_v1" in roles
    assert "Event Analyst" in roles["event_v1"]
    # must not be nested inside quant_v1 string only
    assert "event_v1:" not in (roles.get("quant_v1") or "")


def test_intel_package_marks_unavailable_and_keeps_hypotheses():
    snap = {
        "symbol": "000786.SZ",
        "name": "北新建材",
        "value_available": False,
        "quality_available": False,
        "candidate_sources": ["news", "quant"],
        "research_hypotheses": [
            {
                "type": "HYPOTHESIS",
                "layers": {"FACT": "订单", "INFERENCE": "可能增收", "HYPOTHESIS": "若确认则利润改善"},
                "evidence_ids": ["N1", "E1"],
            }
        ],
        "news_package": {
            "news_data_incomplete": False,
            "news_ids": ["N1"],
            "event_ids": ["E1"],
            "expectation": {"available": False, "note": "无一致预期"},
            "counts": {"last_7d": 1},
            "net_event_score": 0.5,
        },
        "quant": {"leader_score": 0.4},
        "profit_inflection": {"available": False},
        "event": {"score": 0.3},
        "market_regime": "UNKNOWN",
        "market": {"price": 10},
    }
    pkg = build_research_intelligence(snap, role_id="event")
    assert pkg["data_availability"]["value"]["available"] is False
    assert pkg["data_availability"]["consensus_expectation"]["available"] is False
    assert pkg["data_availability"]["industry_map"]["available"] is False
    assert pkg["research_hypotheses"][0]["type"] == "HYPOTHESIS"
    assert "N1" in pkg["evidence_ids"]
    assert "News ≠ BUY" in pkg["rules"]
    assert pkg["candidate_sources"] == ["news", "quant"]


def test_council_payload_contains_intel_package():
    from pathlib import Path

    cfg = {"_root": str(Path(__file__).resolve().parents[1])}
    snap = build_snapshot(
        {
            "symbol": "600000.SH",
            "name": "浦发",
            "candidate_sources": ["quant"],
            "research_hypotheses": [{"type": "HYPOTHESIS", "fact": "x", "evidence_ids": ["N9"]}],
            "value_available": False,
            "news_package": {"news_data_incomplete": True, "expectation": {"available": False}},
            "leader_score": 0.2,
        },
        cfg,
    )
    assert "research_intelligence" in snap
    assert snap["research_intelligence"]["data_availability"]["value"]["available"] is False

    eng = AICouncilEngine(cfg)
    # unconfigured client → heuristic, but payload path still builds intel in _call_role
    out = eng._call_role("event", snap)
    assert out["role"] == "event"
    # prompt must resolve to real event_v1 after yaml fix
    ver, text = eng._prompt_for("event")
    assert ver == "event_v1"
    assert "Event Analyst" in text
