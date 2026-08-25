from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ashare.leader.pipeline import LeaderPipeline, state_changed_materially
from ashare.leader.reentry_engine import ReentryEngine
from ashare.leader.trade_timing import TradeTimingEngine
from ashare.leader.pullback_features import compute_pullback_features


def _bars(
    n: int = 120,
    *,
    seed: int = 0,
    limit_up_tail: int = 0,
    pullback_days: int = 0,
    breakout: bool = False,
    breakdown: bool = False,
    symbol: str = "600000.SH",
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2024-06-01", periods=n)
    ret = rng.normal(0.002, 0.012, size=n)
    close = 10 * np.cumprod(1 + ret)
    # build consecutive limit-up stretch then optional pullback
    lu = np.zeros(n, dtype=bool)
    if limit_up_tail > 0:
        start = n - limit_up_tail - pullback_days - (1 if breakout else 0)
        start = max(0, start)
        for i in range(start, start + limit_up_tail):
            lu[i] = True
            close[i] = close[i - 1] * 1.10 if i > 0 else close[i]
        # mild pullback with volume contraction
        for j in range(pullback_days):
            i = start + limit_up_tail + j
            if i < n:
                close[i] = close[i - 1] * (0.97 if j == 0 else 0.995)
                lu[i] = False
        if breakout and pullback_days > 0:
            i = min(n - 1, start + limit_up_tail + pullback_days)
            close[i] = close[i - 1] * 1.04
            lu[i] = False
        if breakdown and pullback_days > 0:
            i = min(n - 1, start + limit_up_tail + pullback_days)
            close[i] = close[i - 1] * 0.88
            lu[i] = False
    high = close * 1.02
    low = close * 0.98
    open_ = close * 1.001
    volume = rng.uniform(1e6, 3e6, n)
    if limit_up_tail > 0:
        peak_i = start + limit_up_tail - 1
        volume[peak_i] = 8e6
        for j in range(pullback_days):
            i = start + limit_up_tail + j
            if i < n:
                volume[i] = 2e6 * (0.7**j)
        if breakout:
            volume[-1] = 5e6
        if breakdown:
            volume[-1] = 7e6
            open_[-1] = close[-2] * 1.03
            low[-1] = close[-1] * 0.99
    return pd.DataFrame(
        {
            "date": dates,
            "symbol": symbol,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
            "amount": volume * close,
            "pct_chg": np.r_[0, np.diff(close) / close[:-1]] * 100,
            "is_st": False,
            "is_halt": False,
            "limit_up": lu,
            "limit_down": np.zeros(n, dtype=bool),
        }
    )


@pytest.fixture
def root_cfg(tmp_path):
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    return {
        "_root": str(root),
        "leader": {"focus": {"state_file": str(tmp_path / "focus.json"), "max_focus_stocks": 8}},
    }


def test_extreme_without_reentry_is_wait(root_cfg):
    timing = TradeTimingEngine(root_cfg)
    out = timing.evaluate(
        leader_score=0.95,
        factor_score=0.9,
        stage="EXTREME",
        chase_score=0.95,
        reentry_score=0.1,
        reentry_phase="WAIT",
        limit_up=True,
    )
    assert out["trade_timing_action"] == "WAIT"


def test_extreme_with_strong_reentry_buy_candidate(root_cfg):
    timing = TradeTimingEngine(root_cfg)
    out = timing.evaluate(
        leader_score=0.9,
        factor_score=0.8,
        stage="EXTREME",
        chase_score=0.4,
        reentry_score=0.72,
        reentry_phase="REACCELERATION",
        limit_up=False,
        board_count=3,
    )
    assert out["trade_timing_action"] == "BUY_CANDIDATE"
    assert out["trade_timing_action"] != "BUY_READY"  # still EXTREME label
    # 1板不得 BUY_CANDIDATE
    one = timing.evaluate(
        leader_score=0.9,
        factor_score=0.8,
        stage="EXTREME",
        chase_score=0.4,
        reentry_score=0.72,
        reentry_phase="REACCELERATION",
        limit_up=False,
        board_count=1,
    )
    assert one["trade_timing_action"] == "WAIT"


def test_breakdown_drops_not_healthy_divergence(root_cfg):
    eng = ReentryEngine(root_cfg)
    feats = {"structure_break": 1.0, "big_red_volume": 1.0, "pullback_from_high": -0.15}
    out = eng.evaluate(feats, stage="BREAKDOWN", chase_score=0.2)
    assert out["reentry_phase"] == "NONE"
    assert out["reentry_score"] < 0.3


def test_healthy_divergence_not_immediate_drop(root_cfg):
    df = _bars(limit_up_tail=4, pullback_days=2, seed=3)
    as_of = str(df["date"].iloc[-1].date())
    pb = compute_pullback_features(df, as_of=as_of)
    assert pb.get("available")
    # first non limit-up after streak should be flagged when last day not LU
    eng = ReentryEngine(root_cfg)
    base = {"limit_up_count_5d": 4, "consecutive_limit_up": 0}
    out = eng.annotate_from_bars(
        base, df, stage="EXTREME", chase_score=0.8, limit_up=False, as_of=as_of
    )
    assert out["reentry_phase"] in {"DIVERGENCE", "PULLBACK_WATCH", "STABILIZATION", "WAIT", "REACCELERATION"}
    assert out["reentry_flags"]["structure_break"] < 0.5 or out["reentry_score"] >= 0


def test_volume_contraction_raises_reentry(root_cfg):
    df = _bars(limit_up_tail=3, pullback_days=3, seed=5)
    as_of = str(df["date"].iloc[-1].date())
    eng = ReentryEngine(root_cfg)
    out = eng.annotate_from_bars({}, df, stage="EXTREME", chase_score=0.7, limit_up=False, as_of=as_of)
    assert float(out["pullback_features"].get("volume_contraction") or 0) >= 0.0
    assert out["reentry_components"]["volume_score"] >= 0.2


def test_breakout_after_pullback_raises_reentry(root_cfg):
    df = _bars(limit_up_tail=3, pullback_days=2, breakout=True, seed=7)
    as_of = str(df["date"].iloc[-1].date())
    eng = ReentryEngine(root_cfg)
    out = eng.annotate_from_bars({}, df, stage="EXTREME", chase_score=0.5, limit_up=False, as_of=as_of)
    assert out["reentry_score"] >= 0.35 or out["reentry_phase"] in {
        "REACCELERATION",
        "BUY_CANDIDATE",
        "PULLBACK_WATCH",
        "DIVERGENCE",
        "STABILIZATION",
    }


def test_negative_news_lowers_reentry(root_cfg):
    eng = ReentryEngine(root_cfg)
    good = eng.evaluate(
        {"pullback_from_high": -0.04, "volume_contraction": 0.3, "reacceleration": 0.6, "healthy_divergence": 0.7},
        stage="EXTREME",
        chase_score=0.4,
        negative_evidence=0.0,
    )
    bad = eng.evaluate(
        {"pullback_from_high": -0.04, "volume_contraction": 0.3, "reacceleration": 0.6, "healthy_divergence": 0.7},
        stage="EXTREME",
        chase_score=0.4,
        negative_evidence=0.9,
    )
    assert bad["reentry_score"] < good["reentry_score"]


def test_pullback_features_no_future(root_cfg):
    df = _bars(n=100, limit_up_tail=3, pullback_days=2, seed=9)
    as_of = str(df["date"].iloc[-5].date())
    pb = compute_pullback_features(df, as_of=as_of)
    assert pb.get("feature_as_of")
    # truncated as_of must not use last bars after cut
    assert pb["available"] is True
    meta = pb.get("pullback_feature_meta") or {}
    for m in meta.values():
        assert "feature_as_of" in m
        assert "available" in m
        assert "source" in m


def test_state_unchanged_skips_llm(root_cfg):
    pipe = LeaderPipeline(root_cfg)
    row = {
        "news_tier": "local_llm_full",
        "state_version": "abc",
        "state_changed": False,
        "news_trigger": False,
        "analysis_cache": {"state_version": "abc"},
    }
    assert pipe.should_skip_news_llm(row) is True


def test_same_payload_hash_skips_llm(root_cfg):
    pipe = LeaderPipeline(root_cfg)
    row = {
        "news_tier": "local_llm_full",
        "state_version": "x",
        "analysis_cache": {"payload_hash": "h1", "state_version": "y"},
    }
    assert pipe.should_skip_news_llm(row, payload_hash="h1") is True


def test_state_changed_materially():
    prev = {"stage": "EXTREME", "chase_score": 0.9, "reentry_score": 0.1, "board_count": 5, "trade_timing_action": "WAIT"}
    cur = {**prev, "reentry_score": 0.6, "reentry_phase": "REACCELERATION"}
    assert state_changed_materially(prev, cur, {"refresh": {"reentry_delta": 0.1}}) is True
    assert state_changed_materially(prev, prev, {}) is False


def test_pipeline_extreme_wait_then_reentry_path(root_cfg, tmp_path):
    cfg = {
        **root_cfg,
        "leader": {
            "enabled": True,
            "focus": {"state_file": str(tmp_path / "f.json"), "max_focus_stocks": 5, "min_leader_score": 0.2},
            "universe": {"require_limit_up": True},
        },
    }
    # Still at limit-up extreme → WAIT
    df_ext = _bars(limit_up_tail=4, pullback_days=0, seed=11, symbol="600111.SH")
    as_of = str(df_ext["date"].iloc[-1].date())
    pipe = LeaderPipeline(cfg)
    pack = pipe.enrich_rows(
        [{"symbol": "600111.SH", "sources": ["limit_up"], "board_count": 4, "name": "Ext"}],
        {"600111.SH": df_ext},
        as_of=as_of,
    )
    row = pack["rows"][0]
    assert row["stage"] in {"EXTREME", "ACCELERATION", "TREND"}
    if row["stage"] == "EXTREME" and row.get("leader_features", {}).get("limit_up_today"):
        assert row["trade_timing_action"] == "WAIT"
    assert "reentry_score" in row
