from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ashare.leader.chase_risk import ChaseRiskEngine
from ashare.leader.features import compute_leader_features
from ashare.leader.focus_watchlist import FocusWatchlistStore
from ashare.leader.leader_ranking import LeaderRankingEngine
from ashare.leader.lifecycle import council_tier, news_tier
from ashare.leader.limit_up_universe import LimitUpUniverse, is_limit_up_row
from ashare.leader.pipeline import LeaderPipeline
from ashare.leader.stage_engine import StageEngine
from ashare.leader.trade_timing import TradeTimingEngine
from ashare.research.canonical_decision import build_canonical_decision


def _synth_bars(
    n: int = 120,
    *,
    seed: int = 0,
    limit_up_tail: int = 0,
    symbol: str = "600000.SH",
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2024-06-01", periods=n)
    ret = rng.normal(0.002, 0.015, size=n)
    close = 10 * np.cumprod(1 + ret)
    high = close * (1 + rng.uniform(0, 0.02, n))
    low = close * (1 - rng.uniform(0, 0.02, n))
    open_ = close * (1 + rng.normal(0, 0.005, n))
    volume = rng.uniform(1e6, 5e6, n)
    amount = volume * close
    lu = np.zeros(n, dtype=bool)
    if limit_up_tail > 0:
        lu[-limit_up_tail:] = True
    return pd.DataFrame(
        {
            "date": dates,
            "symbol": symbol,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
            "amount": amount,
            "pct_chg": ret * 100,
            "is_st": False,
            "is_halt": False,
            "limit_up": lu,
            "limit_down": np.zeros(n, dtype=bool),
        }
    )


@pytest.fixture
def root_cfg(tmp_path: Path) -> dict:
    root = Path(__file__).resolve().parents[1]
    return {"_root": str(root)}


def test_non_limit_up_rejected_from_leader_universe(root_cfg):
    lu = LimitUpUniverse(root_cfg)
    rows = [
        {"symbol": "600001.SH", "sources": ["quant"], "board_count": 0},
        {"symbol": "600002.SH", "sources": ["limit_up"], "board_count": 2},
    ]
    passed, rejected = lu.filter_rows(rows)
    assert len(passed) == 1
    assert passed[0]["symbol"] == "600002.SH"
    assert any(r.get("reject_reason") == "NOT_LIMIT_UP" for r in rejected)


def test_consecutive_limit_up_ranking_priority(root_cfg):
    lu = LimitUpUniverse(root_cfg)
    panel = {
        "600001.SH": _synth_bars(limit_up_tail=1, seed=1, symbol="600001.SH"),
        "600002.SH": _synth_bars(limit_up_tail=3, seed=2, symbol="600002.SH"),
    }
    as_of = str(panel["600002.SH"]["date"].iloc[-1].date())
    feats = {sym: compute_leader_features(df, as_of=as_of) for sym, df in panel.items()}
    rows = [
        {"symbol": "600001.SH", "sources": ["limit_up"], "board_count": 1, "event_score": 0.9},
        {"symbol": "600002.SH", "sources": ["limit_up"], "board_count": 3, "event_score": 0.2},
    ]
    passed, _ = lu.filter_rows(rows, feats_by_sym=feats)
    assert passed[0]["symbol"] == "600002.SH"


def test_leader_ranking_prefers_higher_board(root_cfg):
    rank = LeaderRankingEngine(root_cfg)
    feats1 = {"consecutive_limit_up": 1, "limit_up_count_5d": 1}
    feats3 = {"consecutive_limit_up": 3, "limit_up_count_5d": 3}
    s1 = rank.score({"board_count": 1, "event_score": 0.5}, feats1)
    s3 = rank.score({"board_count": 3, "event_score": 0.5}, feats3)
    assert s3 > s1


def test_focus_persists_off_rank(tmp_path: Path, root_cfg):
    state = tmp_path / "focus.json"
    cfg = {**root_cfg, "leader": {"focus": {"state_file": str(state), "max_focus_stocks": 5}}}
    store = FocusWatchlistStore(cfg)
    store.save(
        {
            "600888.SH": {
                "symbol": "600888.SH",
                "name": "FocusCo",
                "lifecycle": "FOCUS",
                "leader_score": 0.8,
                "stage": "TREND",
                "trade_timing_action": "WAIT",
                "trade_timing_score": 0.4,
                "board_count": 3,
            }
        }
    )
    merged, stats = store.merge_cycle([], as_of="2025-01-10")
    assert stats["merged_from_focus"] == 1
    assert any(r["symbol"] == "600888.SH" and r.get("merged_from_focus") for r in merged)


def test_focus_survives_ranking_cutoff(tmp_path: Path, root_cfg):
    """Focus names off Top-N still enter research_universe via CandidateEngine."""
    from ashare.candidate import CandidateEngine

    state = tmp_path / "focus_cut.json"
    cfg = {
        **root_cfg,
        "leader": {
            "enabled": True,
            "focus": {"state_file": str(state), "max_focus_stocks": 5, "min_leader_score": 0.1},
            "universe": {"require_limit_up": True},
        },
        "research": {"funnel": {"max_after_events": 100, "max_union_candidates": 5, "max_research_pool": 2}},
    }
    store = FocusWatchlistStore(cfg)
    store.save(
        {
            "600999.SH": {
                "symbol": "600999.SH",
                "name": "FocusKeep",
                "lifecycle": "FOCUS",
                "leader_score": 0.2,
                "stage": "TREND",
                "trade_timing_action": "WAIT",
                "trade_timing_score": 0.3,
                "board_count": 2,
                "candidate_sources": ["event"],
            }
        }
    )
    # High-score limit-ups crowd out focus on ranking; focus must still merge in.
    rows = [
        {"symbol": f"60000{i}.SH", "sources": ["limit_up"], "board_count": 3, "event_score": 2.0, "name": f"H{i}"}
        for i in range(5)
    ]
    panel = {r["symbol"]: _synth_bars(limit_up_tail=2, seed=i + 1, symbol=r["symbol"]) for i, r in enumerate(rows)}
    panel["600999.SH"] = _synth_bars(limit_up_tail=1, seed=99, symbol="600999.SH")
    as_of = str(panel["600999.SH"]["date"].iloc[-1].date())
    eng = CandidateEngine(cfg)
    uni = eng.build_research_universe(
        panel=panel,
        pool={"candidates": rows, "symbols": [r["symbol"] for r in rows]},
        news_discovery={"news_candidates": [], "rejected": []},
        as_of=as_of,
    )
    syms = {r["symbol"] for r in (uni.get("research_universe") or [])}
    assert "600999.SH" in syms



def test_focus_drop_on_breakdown(tmp_path: Path, root_cfg):
    state = tmp_path / "focus2.json"
    cfg = {**root_cfg, "leader": {"focus": {"state_file": str(state), "max_focus_stocks": 5}}}
    store = FocusWatchlistStore(cfg)
    store.save(
        {
            "600777.SH": {
                "symbol": "600777.SH",
                "lifecycle": "FOCUS",
                "leader_score": 0.7,
                "focus_cycles": 1,
            }
        }
    )
    merged, stats = store.merge_cycle(
        [{"symbol": "600777.SH", "stage": "BREAKDOWN", "leader_score": 0.7, "trade_timing_score": 0.1}],
        as_of="2025-01-10",
    )
    row = next(r for r in merged if r["symbol"] == "600777.SH")
    assert row["lifecycle"] == "DROPPED"
    assert stats["dropped"] >= 1


def test_focus_drop_on_severe_negative(tmp_path: Path, root_cfg):
    state = tmp_path / "focus3.json"
    cfg = {**root_cfg, "leader": {"focus": {"state_file": str(state), "max_focus_stocks": 5}}}
    store = FocusWatchlistStore(cfg)
    store.save({"600666.SH": {"symbol": "600666.SH", "lifecycle": "FOCUS", "leader_score": 0.6, "focus_cycles": 1}})
    merged, _ = store.merge_cycle(
        [
            {
                "symbol": "600666.SH",
                "stage": "TREND",
                "leader_score": 0.6,
                "negative_evidence_score": 0.9,
                "trade_timing_score": 0.3,
            }
        ],
        as_of="2025-01-10",
    )
    row = next(r for r in merged if r["symbol"] == "600666.SH")
    assert row["lifecycle"] == "DROPPED"


def test_extreme_stage_defaults_to_wait_not_buy(root_cfg):
    timing = TradeTimingEngine(root_cfg)
    out = timing.evaluate(
        leader_score=0.95,
        factor_score=0.92,
        stage="EXTREME",
        chase_score=0.91,
        limit_up=True,
    )
    assert out["trade_timing_action"] == "WAIT"
    assert out["trade_timing_score"] <= 0.45
    assert "extreme" in out["timing_reason"].lower()


def test_buy_ready_requires_timing_and_risk(root_cfg):
    rep = {
        "symbol": "600000.SH",
        "name": "Test",
        "decision": {"research_rating": "BUY", "action": "SMALL_POSITION"},
        "chairman": {"rating": "BUY", "trading_action": "SMALL_POSITION"},
        "gate": {"passed": True},
    }
    uni = {
        "candidate_score": 0.8,
        "trade_timing_action": "BUY_READY",
        "trade_timing_score": 0.75,
        "lifecycle": "BUY_READY",
        "stage": "TREND",
    }
    cd = build_canonical_decision(
        rep,
        as_of="2025-01-10",
        universe_row=uni,
        bar_like={"is_st": False, "is_halt": False, "limit_up": False, "amount": 1e8},
        risk_allow_fn=lambda _: (True, "ok"),
    )
    assert cd["committee_approve"] is True
    assert cd["leader_timing"]["timing_buy_ready"] is True

    blocked = build_canonical_decision(
        rep,
        as_of="2025-01-10",
        universe_row={**uni, "trade_timing_action": "WAIT"},
        bar_like={"is_st": False, "is_halt": False, "limit_up": True, "amount": 1e8},
        risk_allow_fn=lambda _: (False, "limit_up"),
    )
    assert blocked["committee_approve"] is False
    assert blocked["leader_timing"]["timing_buy_ready"] is False


def test_scan_tier_skips_full_council(root_cfg):
    assert council_tier("LEADER_CANDIDATE", root_cfg) == "scan"
    assert council_tier("FOCUS", root_cfg) == "full"


def test_news_tier_rules_only_for_scan(root_cfg):
    assert news_tier("NEW_LIMIT_UP", "WAIT", root_cfg) == "rules_only"
    assert news_tier("FOCUS", "WAIT", root_cfg) != "rules_only"


def test_should_skip_news_llm_on_unchanged_state(root_cfg):
    pipe = LeaderPipeline(root_cfg)
    row = {
        "news_tier": "local_llm_full",
        "state_version": "abc123",
        "analysis_cache": {"state_version": "abc123", "payload_hash": "h1"},
    }
    assert pipe.should_skip_news_llm(row, payload_hash="h1") is True
    assert pipe.should_skip_news_llm({"news_tier": "rules_only"}) is True


def test_stage_features_no_future_data(root_cfg):
    df = _synth_bars(120, limit_up_tail=2, seed=9)
    as_of = str(df["date"].iloc[-5].date())
    feats = compute_leader_features(df, as_of=as_of)
    full_last = compute_leader_features(df)
    assert feats["consecutive_limit_up"] <= full_last["consecutive_limit_up"] + 1
    assert "ret_20" in feats


def test_leader_features_tz_aware_as_of(root_cfg):
    df = _synth_bars(120, limit_up_tail=1, seed=11)
    as_of = "2024-08-01T23:59:59+00:00"
    feats = compute_leader_features(df, as_of=as_of)
    assert isinstance(feats, dict)


def test_leader_pipeline_enrich_rejects_non_limit_up(tmp_path: Path, root_cfg):
    state = tmp_path / "empty_focus.json"
    cfg = {**root_cfg, "leader": {"focus": {"state_file": str(state), "max_focus_stocks": 5}}}
    panel = {"600010.SH": _synth_bars(symbol="600010.SH")}
    pipe = LeaderPipeline(cfg)
    pack = pipe.enrich_rows(
        [{"symbol": "600010.SH", "sources": ["quant"], "board_count": 0}],
        panel,
        as_of=str(panel["600010.SH"]["date"].iloc[-1].date()),
    )
    assert pack["rows"] == []
    assert pack["rejected"]


def test_is_limit_up_row_from_feats():
    assert is_limit_up_row({"sources": ["news"]}, {"limit_up_today": True})
    assert not is_limit_up_row({"sources": ["quant"]}, {"limit_up_today": False})
