"""CSI300 benchmark + paper fill execution linkage tests."""

from __future__ import annotations

import pandas as pd

from ashare.research.benchmark import csi300_benchmark_returns, resolve_benchmark_pack
from ashare.research.execution_tracking import attach_paper_execution


def test_csi300_benchmark_from_index_df():
    dates = pd.bdate_range("2024-01-02", periods=12)
    idx = pd.DataFrame({"date": dates, "close": [4000.0] * 6 + [4100.0] * 6})
    pack = csi300_benchmark_returns(idx, dates[4], horizons=[5])
    assert pack["method"] == "csi300"
    assert pack["benchmark_available"] is True
    assert pack["returns"]["5"] is not None
    assert abs(float(pack["returns"]["5"]) - 0.025) < 1e-6


def test_resolve_benchmark_falls_back_without_index(monkeypatch):
    panel = {
        "600000.SH": pd.DataFrame(
            {"date": pd.bdate_range("2024-01-02", periods=10), "close": [10.0] * 5 + [11.0] * 5}
        )
    }
    cfg = {
        "_root": ".",
        "research": {"tracking": {"benchmark": "csi300", "benchmark_fallback": "equal_weight_universe"}},
    }
    monkeypatch.setattr(
        "ashare.data.akshare_source.fetch_csi300_index_bars",
        lambda _cfg: pd.DataFrame(),
    )
    pack = resolve_benchmark_pack(cfg, panel, "2024-01-10", horizons=[5])
    assert pack["primary"] == "equal_weight_universe"
    assert pack.get("fallback_from") == "csi300_unavailable"


def test_attach_paper_execution_with_fill():
    dates = pd.bdate_range("2024-01-02", periods=12)
    sym = "600000.SH"
    panel = {sym: pd.DataFrame({"date": dates, "close": [10.0] * 6 + [11.0] * 6})}
    report = {"symbol": sym, "research_time": str(dates[4].date())}
    outcome = {
        "symbol": sym,
        "horizons": {"5": {"actual_return": 0.1, "benchmark_return": 0.02, "excess_return": 0.08}},
    }
    fills = {
        sym: [
            {
                "side": "BUY",
                "price": 10.2,
                "quantity": 100,
                "traded_at": str(dates[5].date()) + "T09:31:00",
            }
        ]
    }
    attach_paper_execution(outcome, report, fills, panel=panel)
    assert outcome["execution"]["available"] is True
    assert outcome["execution"]["fill_price"] == 10.2
    assert "horizons_from_fill" in outcome["execution"]
