from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ashare.factors.engine import FactorEngine, compute_symbol_factors
from ashare.factors.normalize import normalize_cross_section, winsorize_series
from ashare.ml.leakage import FutureLeakageError, LeakageDetector
from ashare.ml.target import attach_excess_target
from ashare.ml.walk_forward import walk_forward_folds
from ashare.portfolio import PortfolioEngine, RiskFilterEngine
from ashare.profit import ProfitInflectionEngine
from ashare.events import EventEngine
from ashare.research.council import DebateEngine
from ashare.research.snapshot import build_snapshot


def _synth_bars(n: int = 180, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2024-01-02", periods=n)
    ret = rng.normal(0.001, 0.02, size=n)
    close = 10 * np.cumprod(1 + ret)
    high = close * (1 + rng.uniform(0, 0.02, n))
    low = close * (1 - rng.uniform(0, 0.02, n))
    open_ = close * (1 + rng.normal(0, 0.005, n))
    volume = rng.uniform(1e6, 5e6, n)
    amount = volume * close
    return pd.DataFrame(
        {
            "date": dates,
            "symbol": "600000.SH",
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
            "amount": amount,
            "pct_chg": ret * 100,
            "is_st": False,
            "is_halt": False,
            "limit_up": False,
            "limit_down": False,
        }
    )


def test_momentum_and_no_lookahead_shift():
    df = _synth_bars()
    out = compute_symbol_factors(df)
    # momentum_5d uses past close only
    i = 20
    expected = float(df["close"].iloc[i] / df["close"].iloc[i - 5] - 1)
    assert out["momentum_5d"].iloc[i] == pytest.approx(expected, rel=1e-9)
    assert pd.isna(out["pe"].iloc[i])  # value stub never fabricated


def test_normalize_cross_section_by_date():
    rows = []
    for sym, seed in [("A", 1), ("B", 2), ("C", 3)]:
        d = _synth_bars(80, seed=seed)
        d["symbol"] = sym
        rows.append(compute_symbol_factors(d))
    raw = pd.concat(rows, ignore_index=True)
    z = normalize_cross_section(raw, ["momentum_20d"])
    g = z[z["date"] == z["date"].max()]
    assert abs(float(g["momentum_20d"].mean())) < 1e-6 or len(g) < 2


def test_leader_score_weights_sum():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    eng = FactorEngine({"_root": str(root)})
    w = eng.catalog.leader_weights
    assert abs(sum(w.values()) - 1.0) < 1e-9
    panel = {"600000.SH": _synth_bars(), "600001.SH": _synth_bars(seed=1)}
    rows = eng.asof_rows(panel)
    assert rows
    assert "leader_score" in rows[0]
    assert rows[0]["value_available"] is False


def test_profit_inflection_quality_d():
    eng = ProfitInflectionEngine()
    r = eng.score_from_forecast_meta(
        {"symbol": "600000.SH", "forecast_type": "预减", "yoy_pct": -30}
    )
    assert r.quality == "D"
    fin = eng.score_from_financials("600000.SH", [])
    assert fin.available is False


def test_event_score_bounds():
    eng = EventEngine()
    rows = eng.enrich_candidates(
        [{"symbol": "600000.SH", "sources": ["limit_up"], "event_tags": ["涨停"], "profit_gap_score": 1}]
    )
    assert -1.0 <= rows[0]["event_score"] <= 1.0
    assert rows[0]["events"]


def test_excess_target_and_leakage():
    df = _synth_bars()
    df["symbol"] = "600000.SH"
    panel = pd.concat([df, _synth_bars(seed=2).assign(symbol="600001.SH")], ignore_index=True)
    from ashare.factors.engine import compute_symbol_factors, _add_cross_section_market_rs

    parts = []
    for sym, g in panel.groupby("symbol"):
        e = compute_symbol_factors(g)
        e["symbol"] = sym
        parts.append(e)
    raw = _add_cross_section_market_rs(pd.concat(parts, ignore_index=True))
    data = attach_excess_target(raw, horizon=5)
    assert "target" in data.columns
    det = LeakageDetector()
    with pytest.raises(FutureLeakageError):
        det.check_feature_before_label(data, ["momentum_5d", "target"])
    det.validate_train_bundle(data.dropna(subset=["target"]), ["momentum_5d", "momentum_20d"], "walk_forward")
    with pytest.raises(FutureLeakageError):
        det.check_no_random_split_api("random")


def test_walk_forward_no_overlap():
    df = _synth_bars(400)
    df["symbol"] = "X"
    df["target"] = 0.01
    folds = walk_forward_folds(df, train_years=1, test_years=1, embargos_days=5)
    assert folds
    for f in folds:
        if f.train.empty or f.test.empty:
            continue
        assert f.train["date"].max() < f.test["date"].min()


def test_portfolio_conflict_and_risk():
    port = PortfolioEngine({})
    align = port.signal_alignment({"ml_z": -0.5, "leader_z": 1.0, "momentum_z": 0.2})
    assert align["state"] == "conflict"
    assert align["scale"] <= 0.5
    risk = RiskFilterEngine({})
    ok, reason = risk.allow_open({"is_st": True})
    assert not ok and reason == "st"


def test_debate_trigger_and_snapshot():
    deb = DebateEngine({})
    opinions = {
        "fundamental": {"stance": "bull", "points": ["a"], "falsify": "x"},
        "bear": {"stance": "bear", "points": ["b"]},
        "quant": {"stance": "bull"},
        "event": {"stance": "neutral"},
        "valuation": {"stance": "neutral", "status": "unavailable"},
    }
    assert deb.needs_debate(opinions)
    rounds = deb.run({"symbol": "600000.SH"}, opinions)
    assert 1 <= len(rounds) <= 2
    snap = build_snapshot(
        {
            "symbol": "600000.SH",
            "name": "测试",
            "leader_score": 1.0,
            "value_available": False,
            "trigger": {"type": "事件", "score": 0.5},
        },
        {"_root": str(__import__("pathlib").Path(__file__).resolve().parents[1])},
    )
    assert snap["research_id"].startswith("R")
    assert "versions" in snap


def test_winsorize():
    s = pd.Series([1, 2, 3, 4, 100.0])
    w = winsorize_series(s, 0.2, 0.8)
    assert w.max() < 100
