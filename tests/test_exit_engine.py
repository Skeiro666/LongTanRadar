from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from ashare.portfolio.exit.config import load_exit_config, soft_action
from ashare.portfolio.exit.features import compute_exit_features
from ashare.portfolio.exit.heuristic import compute_exit_score
from ashare.portfolio.exit.labels import assert_features_asof, forward_returns
from ashare.portfolio.exit.engine import ExitEngine
from ashare.portfolio.exit.quality import classify_exit_timing, summarize_exit_quality
from ashare.portfolio.exit.thesis_decay import evaluate_thesis_decay
from ashare.portfolio.exit.notify import maybe_build_alpha_exit_notification
from ashare.portfolio.exit.backtest import run_exit_backtest
from ashare.portfolio.exit.alpha import build_exit_alpha
from ashare.portfolio.exit.calibration import calibrate_exit_scores
from ashare.portfolio.exit.ml_exit import train_exit_ml, predict_exit_ml


def _synth_bars(n: int = 80, seed: int = 42, start: float = 10.0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = [date(2024, 1, 2) + timedelta(days=i) for i in range(n)]
    # skip weekends roughly by using business-ish consecutive days for simplicity
    rets = rng.normal(0.001, 0.02, size=n)
    close = start * np.cumprod(1 + rets)
    high = close * (1 + rng.uniform(0, 0.01, n))
    low = close * (1 - rng.uniform(0, 0.01, n))
    open_ = close * (1 + rng.normal(0, 0.002, n))
    vol = rng.integers(1_000_000, 5_000_000, n).astype(float)
    return pd.DataFrame(
        {
            "date": dates,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": vol,
            "amount": vol * close,
        }
    )


def test_load_exit_config():
    cfg = load_exit_config({"_root": "."})
    assert "thresholds" in cfg
    assert soft_action(0.1, cfg["thresholds"]) == "HOLD"
    assert soft_action(0.7, cfg["thresholds"]) == "REDUCE"
    assert soft_action(0.9, cfg["thresholds"]) == "EXIT"


def test_exit_features_missing_bars():
    pack = compute_exit_features(bars=pd.DataFrame(), as_of=date(2024, 6, 1), position={"symbol": "000001.SZ"})
    assert pack["features"]["trend_decay"]["available"] is False
    assert pack["features"]["news_reversal"]["available"] is False


def test_exit_features_asof_no_lookahead():
    bars = _synth_bars(60)
    as_of = bars["date"].iloc[40]
    # inject future spike that must not affect as_of features
    bars.loc[bars.index[-1], "close"] = float(bars.loc[bars.index[-1], "close"]) * 10
    pack = compute_exit_features(
        bars=bars,
        as_of=as_of,
        position={"symbol": "000001.SZ", "entry_price": 10.0, "entry_date": "2024-01-10"},
    )
    assert assert_features_asof(pack, bars, as_of)
    assert pack["as_of"] == pd.Timestamp(as_of).date().isoformat()
    # current price should be as_of close not future spike
    hist = bars[pd.to_datetime(bars["date"]).dt.date <= pd.Timestamp(as_of).date()]
    assert abs(float(pack["current_price"]) - float(hist.iloc[-1]["close"])) < 1e-6


def test_exit_heuristic_actions():
    bars = _synth_bars(80, seed=7)
    as_of = bars["date"].iloc[-1]
    pack = compute_exit_features(
        bars=bars,
        as_of=as_of,
        position={
            "symbol": "600000.SH",
            "entry_price": float(bars.iloc[20]["close"]),
            "entry_date": str(bars.iloc[20]["date"]),
            "max_favorable_price": float(bars["high"].max()),
        },
        news={"prior_direction": "positive", "direction": "negative"},
        event={"event_state": "COMPLETED"},
    )
    score = compute_exit_score(pack)
    assert score["mode"] == "HEURISTIC"
    assert score["available"] is True
    assert 0 <= score["exit_score"] <= 1
    assert score["action"] in {"HOLD", "REDUCE", "EXIT"}


def test_exit_engine_evaluate():
    bars = _synth_bars(70)
    eng = ExitEngine({"_root": "."})
    out = eng.evaluate(
        symbol="000786.SZ",
        bars=bars,
        as_of=bars["date"].iloc[-1],
        position={"entry_price": 10.0, "entry_date": str(bars.iloc[5]["date"]), "cost_price": 10.0},
    )
    assert out["symbol"] == "000786.SZ"
    assert out["action"] in {"HOLD", "REDUCE", "EXIT"}
    assert "expected_return_5d" in out
    assert out["expected_return_source"] in {"HEURISTIC", "MODEL"}


def test_forward_labels_and_asof():
    bars = _synth_bars(50)
    sd = bars["date"].iloc[20]
    fr = forward_returns(bars, signal_date=sd, horizons=[1, 5, 10])
    assert fr["available"] is True
    assert fr["5"]["available"] is True
    # last day — future missing
    fr2 = forward_returns(bars, signal_date=bars["date"].iloc[-1], horizons=[5])
    assert fr2["5"]["available"] is False


def test_exit_quality_classes():
    good = classify_exit_timing(exit_price=20.0, post_return_5d=-0.05, drawdown_at_exit=0.02)
    assert good["class"] == "GOOD"
    early = classify_exit_timing(exit_price=20.0, post_return_5d=0.08, drawdown_at_exit=0.01)
    assert early["class"] == "EARLY"
    late = classify_exit_timing(exit_price=20.0, post_return_5d=-0.01, drawdown_at_exit=0.15)
    assert late["class"] == "LATE"
    summary = summarize_exit_quality([good, early, late] * 12, minimum_sample=30)
    assert summary["available"] is True
    insuf = summarize_exit_quality([good], minimum_sample=30)
    assert insuf["status"] == "INSUFFICIENT_SAMPLE"


def test_thesis_decay():
    out = evaluate_thesis_decay(
        buy_thesis={"event_state": "ACTIVE", "news_direction": "positive", "momentum": 0.1},
        current={"event_state": "COMPLETED", "news_direction": "negative", "momentum": -0.05},
    )
    assert out["available"] is True
    assert out["level"] in {"HIGH", "MEDIUM", "LOW"}


def test_alpha_exit_notification():
    note = maybe_build_alpha_exit_notification(
        {
            "symbol": "000001.SZ",
            "exit_score": 0.75,
            "action": "EXIT",
            "reason_texts": ["动量衰减"],
            "expected_return_5d": -0.01,
            "expected_return_10d": -0.02,
        },
        {"_root": "."},
    )
    assert note is not None
    assert note["level"] == "ALPHA_EXIT"
    none = maybe_build_alpha_exit_notification({"exit_score": 0.2, "action": "HOLD"}, {"_root": "."})
    assert none is None


def test_exit_backtest_and_alpha_insufficient_or_ok():
    bars = {"000001.SZ": _synth_bars(100, seed=1)}
    entries = [{"symbol": "000001.SZ", "entry_date": "2024-01-15", "entry_price": 10.0}] * 5
    bt = run_exit_backtest(bars, entries, cfg={"_root": "."}, minimum_sample=30)
    # 5 samples < 30 → insufficient
    assert bt["strategies"]["exit_engine"]["status"] == "INSUFFICIENT_SAMPLE"
    alpha = build_exit_alpha(bars, entries, cfg={"_root": "."})
    assert alpha["strategies"][0]["status"] == "INSUFFICIENT_SAMPLE"


def test_calibration_buckets():
    bars = {"000001.SZ": _synth_bars(80)}
    rows = [
        {"symbol": "000001.SZ", "signal_date": str(bars["000001.SZ"]["date"].iloc[40]), "exit_score": 0.1},
        {"symbol": "000001.SZ", "signal_date": str(bars["000001.SZ"]["date"].iloc[41]), "exit_score": 0.5},
        {"symbol": "000001.SZ", "signal_date": str(bars["000001.SZ"]["date"].iloc[42]), "exit_score": 0.9},
    ]
    cal = calibrate_exit_scores(rows, bars, cfg={"_root": "."})
    assert "buckets" in cal
    assert len(cal["buckets"]) == 5


def test_ml_insufficient_sample():
    res = train_exit_ml([], cfg={"_root": "."})
    assert res["status"] == "INSUFFICIENT_SAMPLE"
    pred = predict_exit_ml({"features": {}}, cfg={"_root": "."})
    assert pred["available"] is False


def test_hold_reduce_exit_mapping():
    thr = {"hold_max": 0.3, "hold_reduce_max": 0.6, "reduce_max": 0.8}
    assert soft_action(0.0, thr) == "HOLD"
    assert soft_action(0.45, thr) == "HOLD"
    assert soft_action(0.65, thr) == "REDUCE"
    assert soft_action(0.95, thr) == "EXIT"
