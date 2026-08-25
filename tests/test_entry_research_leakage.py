"""Strict as-of / no look-ahead tests for entry research & reentry features."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ashare.leader.entry_validation import (
    ENTRY_MODES,
    build_symbol_samples,
    detect_entry_mode,
    _fwd_labels,
)
from ashare.leader.features import compute_leader_features
from ashare.leader.pullback_features import compute_pullback_features
from ashare.leader.reentry_engine import ReentryEngine
from ashare.leader.chase_risk import ChaseRiskEngine
from ashare.leader.stage_engine import StageEngine


def _bars(n: int = 120, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2024-01-02", periods=n)
    close = 10 + np.cumsum(rng.normal(0, 0.15, size=n))
    close = np.maximum(close, 1.0)
    high = close * (1 + rng.uniform(0, 0.02, size=n))
    low = close * (1 - rng.uniform(0, 0.02, size=n))
    open_ = close * (1 + rng.normal(0, 0.005, size=n))
    vol = rng.integers(1_000_000, 5_000_000, size=n).astype(float)
    lu = np.zeros(n, dtype=bool)
    # plant a 4-board streak ending at n-15
    for k in range(4):
        lu[n - 20 + k] = True
        close[n - 20 + k] = close[n - 21 + k] * 1.10
        high[n - 20 + k] = close[n - 20 + k]
    # mild pullback then bounce
    close[n - 16] = close[n - 17] * 0.97
    close[n - 15] = close[n - 16] * 0.99
    close[n - 14] = close[n - 15] * 1.04
    high[n - 14] = max(high[n - 14], close[n - 14])
    return pd.DataFrame(
        {
            "date": dates,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": vol,
            "amount": vol * close,
            "limit_up": lu,
            "limit_down": np.zeros(n, dtype=bool),
        }
    )


def test_pullback_features_ignore_future_mutation():
    df = _bars()
    as_of = str(df["date"].iloc[-10].date())
    a = compute_pullback_features(df, as_of=as_of)
    mutated = df.copy()
    mutated.loc[mutated.index[-5]:, "close"] *= 3.0
    mutated.loc[mutated.index[-5]:, "high"] *= 3.0
    b = compute_pullback_features(mutated, as_of=as_of)
    for k in (
        "pullback_from_high",
        "reacceleration",
        "breakout_after_pullback",
        "distance_to_ma5",
        "volume_ratio_to_peak",
    ):
        assert a.get(k) == pytest.approx(b.get(k), rel=1e-9, abs=1e-12), k
    assert a.get("feature_as_of") == as_of


def test_leader_features_board_count_asof():
    df = _bars()
    as_of = str(df["date"].iloc[-10].date())
    feats = compute_leader_features(df, as_of=as_of)
    hist = df[pd.to_datetime(df["date"]).dt.normalize() <= pd.Timestamp(as_of).normalize()]
    # consecutive from hist only
    lu = hist["limit_up"].astype(bool).tolist()
    streak = 0
    for x in reversed(lu):
        if x:
            streak += 1
        else:
            break
    assert int(feats.get("consecutive_limit_up") or 0) == streak


def test_stage_chase_reentry_stable_under_future_spike():
    df = _bars()
    as_of = str(df["date"].iloc[-12].date())
    hist = df[pd.to_datetime(df["date"]) <= pd.Timestamp(as_of)]
    feats = compute_leader_features(hist, as_of=as_of)
    stage = StageEngine().classify(feats, {"board_count": int(feats.get("consecutive_limit_up") or 0)})
    chase = ChaseRiskEngine().score(feats, stage=stage)
    re1 = ReentryEngine().annotate_from_bars(
        feats, hist, stage=stage, chase_score=chase, limit_up=bool(feats.get("limit_up_today")), as_of=as_of
    )
    spiked = df.copy()
    spiked.loc[spiked.index[-8]:, ["close", "high", "open", "low"]] *= 5.0
    hist2 = spiked[pd.to_datetime(spiked["date"]) <= pd.Timestamp(as_of)]
    feats2 = compute_leader_features(hist2, as_of=as_of)
    stage2 = StageEngine().classify(feats2, {"board_count": int(feats2.get("consecutive_limit_up") or 0)})
    chase2 = ChaseRiskEngine().score(feats2, stage=stage2)
    re2 = ReentryEngine().annotate_from_bars(
        feats2, hist2, stage=stage2, chase_score=chase2, limit_up=bool(feats2.get("limit_up_today")), as_of=as_of
    )
    assert stage == stage2
    assert chase == pytest.approx(chase2)
    assert re1["reentry_score"] == pytest.approx(re2["reentry_score"])
    assert re1["reentry_phase"] == re2["reentry_phase"]


def test_fwd_labels_are_future_only_and_not_in_features():
    df = _bars()
    i = len(df) - 25
    labels = _fwd_labels(df, i)
    assert "t+1" in labels and labels["t+1"] is not None
    assert "mfe" in labels and "mae" in labels
    as_of = str(df["date"].iloc[i].date())
    feats = compute_leader_features(df.iloc[: i + 1], as_of=as_of)
    pb = compute_pullback_features(df.iloc[: i + 1], as_of=as_of)
    leaked = set(feats) & {"t+1", "t+5", "mfe", "mae", "max_drawdown", "gap_down"}
    leaked |= set(pb) & {"t+1", "t+5", "mfe", "mae"}
    assert not leaked


def test_entry_mode_exclusive_priority():
    # limit-up chase wins
    assert (
        detect_entry_mode(
            limit_up=True,
            board=4,
            first_non_lu=True,
            days_since_lu=0,
            pb={"reacceleration": 0.9, "breakout_after_pullback": 1.0},
            re_phase="REACCELERATION",
        )
        == "DIRECT_CHASE"
    )
    # reaccel over pullback
    assert (
        detect_entry_mode(
            limit_up=False,
            board=0,
            first_non_lu=False,
            days_since_lu=3,
            pb={
                "reacceleration": 0.7,
                "had_prior_pullback": 1.0,
                "pullback_from_high": -0.04,
                "volume_contraction": 0.2,
                "structure_break": 0.0,
            },
            re_phase="REACCELERATION",
        )
        == "REACCELERATION"
    )
    # first divergence day
    assert (
        detect_entry_mode(
            limit_up=False,
            board=3,
            first_non_lu=True,
            days_since_lu=1,
            pb={"pullback_from_high": -0.01, "volume_contraction": 0.05, "structure_break": 0.0},
            re_phase="WAIT",
        )
        == "FIRST_DIVERGENCE"
    )


def test_build_symbol_samples_no_duplicate_mode_same_day():
    df = _bars(160)
    samples = build_symbol_samples(df, "TEST.SZ")
    seen = set()
    for s in samples:
        key = (s.date, s.entry_mode)
        assert key not in seen
        seen.add(key)
        assert s.entry_mode in ENTRY_MODES
        # labels present, features must not equal future peek via as_of cut
        assert s.labels.get("t+1") is not None


def test_breakout_uses_prior_pullback_not_same_bar_contradiction():
    df = _bars()
    as_of = str(df["date"].iloc[-14].date())
    pb = compute_pullback_features(df, as_of=as_of)
    # Feature must be defined; prior-pullback path should be computable without requiring
    # same-day pullback_from_high < -3% AND near high.
    assert "breakout_after_pullback" in pb
    assert "had_prior_pullback" in pb
