"""V5.2 benchmark, alpha layers, roundtable schedule tests."""

from __future__ import annotations

import json
from datetime import date

import pandas as pd

from ashare.research.benchmark import (
    benchmark_snapshot,
    resolve_dual_benchmark_pack,
    should_run_roundtable,
)
from ashare.research.tracking import TrackingEngine


def test_dual_benchmark_snapshot_csi300_ok(monkeypatch):
    dates = pd.bdate_range("2024-01-02", periods=12)
    panel = {
        "600000.SH": pd.DataFrame({"date": dates, "close": [10.0] * 6 + [11.0] * 6}),
    }
    idx = pd.DataFrame({"date": dates, "close": [4000.0] * 6 + [4100.0] * 6})
    monkeypatch.setattr("ashare.data.akshare_source.fetch_csi300_index_bars", lambda _cfg: idx)
    cfg = {"_root": ".", "research": {"tracking": {"benchmark": "csi300"}}}
    pack = resolve_dual_benchmark_pack(cfg, panel, dates[4], horizons=[5])
    snap = pack["snapshot"]
    assert snap["requested"] == "csi300"
    assert snap["actual"] == "csi300"
    assert snap["fallback"] is False
    assert pack["market_returns"]["5"] is not None
    assert pack["universe_returns"]["5"] is not None


def test_dual_benchmark_fallback_honest(monkeypatch):
    dates = pd.bdate_range("2024-01-02", periods=12)
    panel = {
        "600000.SH": pd.DataFrame({"date": dates, "close": [10.0] * 6 + [11.0] * 6}),
    }
    monkeypatch.setattr(
        "ashare.data.akshare_source.fetch_csi300_index_bars",
        lambda _cfg: pd.DataFrame(),
    )
    cfg = {"_root": ".", "research": {"tracking": {"benchmark": "csi300"}}}
    pack = resolve_dual_benchmark_pack(cfg, panel, dates[4], horizons=[5])
    snap = pack["snapshot"]
    assert snap["requested"] == "csi300"
    assert snap["actual"] == "equal_weight_universe"
    assert snap["fallback"] is True
    assert snap["fallback_reason"] == "csi300_unavailable"


def test_market_and_selection_alpha_in_outcomes():
    dates = pd.bdate_range("2024-01-02", periods=12)
    sym = "600000.SH"
    panel = {sym: pd.DataFrame({"date": dates, "close": [10.0] * 6 + [12.0] * 6})}
    report = {"symbol": sym, "research_id": "R1", "research_time": str(dates[4].date())}
    out = TrackingEngine({}).outcomes_for_report(
        report,
        panel,
        market_benchmark_returns={"5": 0.02},
        universe_benchmark_returns={"5": 0.05},
    )
    h5 = out["horizons"]["5"]
    assert abs(h5["actual_return"] - 0.2) < 1e-6
    assert abs(h5["market_alpha"] - 0.18) < 1e-6
    assert abs(h5["selection_alpha"] - 0.15) < 1e-6


def test_roundtable_sampled_skips(tmp_path, monkeypatch):
    cfg = {
        "_root": str(tmp_path),
        "ai": {"roundtable": True, "roundtable_mode": "sampled", "roundtable_sample_every": 3},
    }
    path = tmp_path / "data" / "cache" / "roundtable_schedule.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"run_count": 1}), encoding="utf-8")
    run, reason = should_run_roundtable(cfg, as_of=date(2024, 1, 10))
    assert run is False
    assert "skip" in reason
    path.write_text(json.dumps({"run_count": 2}), encoding="utf-8")
    run2, _ = should_run_roundtable(cfg, as_of=date(2024, 1, 10))
    assert run2 is True


def test_benchmark_snapshot_shape():
    snap = benchmark_snapshot(
        requested="csi300",
        actual="csi300",
        as_of="2024-01-10",
        index="000300",
        fallback=False,
    )
    assert snap["requested"] == "csi300"
    assert snap["fallback"] is False
