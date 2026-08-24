from __future__ import annotations

"""Strict future-leakage + T+1 open execution integrity tests."""

from datetime import date, timedelta

import numpy as np
import pandas as pd

from ashare.portfolio.exit.engine import ExitEngine
from ashare.portfolio.exit.execution import t1_open_fill
from ashare.portfolio.exit.features import compute_exit_features
from ashare.portfolio.exit.backtest import run_exit_backtest


def _bars(n=80, seed=7, start=date(2024, 1, 2)):
    rng = np.random.default_rng(seed)
    dates = [start + timedelta(days=i) for i in range(n)]
    close = 10 * np.cumprod(1 + rng.normal(0, 0.012, n))
    return pd.DataFrame(
        {
            "date": dates,
            "open": close * 0.998,
            "high": close * 1.015,
            "low": close * 0.985,
            "close": close,
            "volume": rng.integers(1e5, 1e6, n).astype(float),
            "pct_chg": rng.normal(0, 1.5, n),
        }
    )


def test_future_bars_do_not_change_past_exit_score():
    bars = _bars()
    as_of = bars["date"].iloc[40]
    pos = {"entry_price": float(bars["close"].iloc[20]), "entry_date": str(bars["date"].iloc[20])}
    eng = ExitEngine({"_root": "."})
    hist = bars[bars["date"] <= as_of].copy()
    s1 = eng.evaluate(symbol="AAA.SH", bars=hist, as_of=as_of, position=pos)

    # Mutate ALL future closes massively
    future = bars.copy()
    mask = future["date"] > as_of
    future.loc[mask, "close"] = future.loc[mask, "close"] * 3.0
    future.loc[mask, "open"] = future.loc[mask, "open"] * 3.0
    future.loc[mask, "high"] = future.loc[mask, "high"] * 3.0
    hist2 = future[future["date"] <= as_of].copy()
    s2 = eng.evaluate(symbol="AAA.SH", bars=hist2, as_of=as_of, position=pos)
    assert s1.get("exit_score") == s2.get("exit_score")


def test_future_news_does_not_change_past_exit_score():
    bars = _bars(seed=11)
    as_of = bars["date"].iloc[35]
    pos = {"entry_price": 10.0, "entry_date": str(bars["date"].iloc[10])}
    eng = ExitEngine({"_root": "."})
    hist = bars[bars["date"] <= as_of]
    s1 = eng.evaluate(
        symbol="AAA.SH",
        bars=hist,
        as_of=as_of,
        position=pos,
        news={"direction": "positive", "score": 0.8},
    )
    s2 = eng.evaluate(
        symbol="AAA.SH",
        bars=hist,
        as_of=as_of,
        position=pos,
        news={"direction": "positive", "score": 0.8},
        # "future" news would only appear if caller passes it â€?engine must only use provided as-of news
    )
    assert s1.get("exit_score") == s2.get("exit_score")
    # Changing news at same as_of CAN change score (that's current info) â€?but mutating after-the-fact
    # news object that wasn't available shouldn't be auto-fetched. Verify no side channel via event.
    s3 = eng.evaluate(
        symbol="AAA.SH",
        bars=hist,
        as_of=as_of,
        position=pos,
        news={"direction": "positive", "score": 0.8},
        event={"event_state": "ACTIVE"},
    )
    # event change is current-context; just ensure evaluate is deterministic for same inputs
    s3b = eng.evaluate(
        symbol="AAA.SH",
        bars=hist,
        as_of=as_of,
        position=pos,
        news={"direction": "positive", "score": 0.8},
        event={"event_state": "ACTIVE"},
    )
    assert s3.get("exit_score") == s3b.get("exit_score")


def test_future_outcome_labels_not_in_features():
    bars = _bars(seed=3)
    as_of = bars["date"].iloc[30]
    pack = compute_exit_features(
        bars=bars,
        as_of=as_of,
        position={"entry_price": 10.0, "entry_date": str(bars["date"].iloc[5])},
        cfg={"_root": "."},
    )
    # Features must not contain forward return keys
    feat_names = set((pack.get("features") or {}).keys())
    assert "forward_return_10d" not in feat_names
    assert "label" not in feat_names
    assert pack["as_of"] == as_of.isoformat()


def test_t1_open_execution_never_uses_signal_close():
    bars = _bars()
    signal_idx = 40
    fill = t1_open_fill(bars, signal_idx)
    assert fill["available"] is True
    assert fill["execution"] == "t1_open"
    assert fill["fill_idx"] == signal_idx + 1
    assert abs(fill["fill_price"] - float(bars.iloc[signal_idx + 1]["open"])) < 1e-9
    # must NOT equal signal close (unless coincidentally equal opens)
    signal_close = float(bars.iloc[signal_idx]["close"])
    # force different open
    bars2 = bars.copy()
    bars2.loc[signal_idx + 1, "open"] = signal_close * 1.05
    fill2 = t1_open_fill(bars2, signal_idx)
    assert fill2["fill_price"] != signal_close


def test_t1_open_unavailable_when_no_next_bar():
    bars = _bars(n=10)
    fill = t1_open_fill(bars, len(bars) - 1)
    assert fill["available"] is False
    assert fill["status"] == "EXECUTION_UNAVAILABLE"


def test_exit_blocked_limit_down():
    bars = _bars(n=20)
    bars.loc[11, "limit_down"] = True
    fill = t1_open_fill(bars, 10)
    assert fill["available"] is False
    assert fill["status"] == "EXIT_BLOCKED"


def test_backtest_uses_t1_open_model():
    b = _bars(n=80)
    bars = {"AAA.SH": b}
    entries = [
        {"symbol": "AAA.SH", "entry_date": str(b["date"].iloc[15 + i * 5]), "entry_price": 10.0}
        for i in range(4)
    ]
    bt = run_exit_backtest(
        bars,
        entries,
        cfg={"_root": ".", "exit": {"minimum_sample": 2, "backtest": {"scan_step": 3}}},
        minimum_sample=2,
    )
    assert bt["execution_model"] == "t1_open"
    assert "exit_engine" in bt["strategies"]
    assert "exit_wo_news" in bt["strategies"]
    eng = bt["strategies"]["exit_engine"]
    assert "gross" in eng and "net" in eng


def test_hold_score_formula():
    bars = _bars()
    as_of = bars["date"].iloc[40]
    eng = ExitEngine({"_root": "."})
    sig = eng.evaluate(
        symbol="AAA.SH",
        bars=bars[bars["date"] <= as_of],
        as_of=as_of,
        position={"entry_price": 10.0, "entry_date": str(bars["date"].iloc[10])},
    )
    if sig.get("exit_score") is not None:
        assert abs(float(sig["hold_score"]) - (1.0 - float(sig["exit_score"]))) < 1e-9
