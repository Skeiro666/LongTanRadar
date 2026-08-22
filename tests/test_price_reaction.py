from __future__ import annotations

import pandas as pd

from ashare.research.intel_package import build_research_intelligence
from ashare.research.price_reaction import annotate_news_candidate_price, classify_price_in_risk, compute_price_reaction
from ashare.research.snapshot import build_snapshot


def _bars(*, closes: list[float], start: str = "2024-01-02") -> pd.DataFrame:
    dates = pd.bdate_range(start, periods=len(closes))
    return pd.DataFrame(
        {
            "date": dates,
            "open": closes,
            "high": [c * 1.01 for c in closes],
            "low": [c * 0.99 for c in closes],
            "close": closes,
            "volume": [1_000_000] * len(closes),
            "limit_up": [False] * len(closes),
            "limit_down": [False] * len(closes),
            "is_st": [False] * len(closes),
            "is_halt": [False] * len(closes),
        }
    )


def test_classify_price_in_high_when_already_ran():
    assert classify_price_in_risk(ret_since_event=0.10, abs_ret_1d=0.05, limit_up=False, limit_down=False, news_direction="BULLISH") == "HIGH"
    assert classify_price_in_risk(ret_since_event=0.05, abs_ret_1d=0.05, limit_up=False, limit_down=False, news_direction="BULLISH") == "MEDIUM"
    assert classify_price_in_risk(ret_since_event=0.01, abs_ret_1d=0.01, limit_up=False, limit_down=False, news_direction="BULLISH") == "LOW"


def test_compute_separates_news_and_price_signal():
    df = _bars(closes=[10, 10.1, 10.2, 11.5])  # last day +~12% vs prior
    rx = compute_price_reaction(df, news_direction="BULLISH", event_time=str(df["date"].iloc[-1].date()))
    assert rx["available"] is True
    assert rx["news_signal"] == "BULLISH"
    assert rx["price_signal"] in {"UP", "FLAT", "DOWN"}
    assert rx["price_in_risk"] in {"HIGH", "MEDIUM", "LOW"}
    assert "not auto" in (rx.get("warning") or "").lower() or "PASS" in (rx.get("warning") or "")


def test_no_bars_available_false():
    rx = compute_price_reaction(None, news_direction="BULLISH")
    assert rx["available"] is False
    assert rx["price_in_risk"] == "UNKNOWN"


def test_high_price_in_does_not_force_trading_action():
    """price_in_risk=HIGH must remain a research warning; snapshot/intel never invent PASS/SELL."""
    df = _bars(closes=[10.0, 10.0, 10.0, 11.2])
    nc = {
        "symbol": "000001.SZ",
        "event_direction": "BULLISH",
        "event_time": str(df["date"].iloc[-1].date()),
        "published_at": str(df["date"].iloc[-1].date()),
        "event_impact": 0.8,
        "confidence": 0.9,
    }
    out = annotate_news_candidate_price(nc, {"000001.SZ": df})
    assert out["price_in_risk"] == "HIGH"
    assert "trading_action" not in out
    assert out.get("status") != "REJECTED"

    snap = build_snapshot(
        {
            "symbol": "000001.SZ",
            "candidate_sources": ["news"],
            "news_discovery": out,
            "price_in_risk": out["price_in_risk"],
            "research_hypotheses": [{"type": "HYPOTHESIS", "evidence_ids": ["N1"]}],
            "value_available": False,
        },
        {"_root": "."},
    )
    pkg = build_research_intelligence(snap)
    assert pkg["price_in_risk"] == "HIGH"
    assert pkg["price_reaction"]["available"] is True
    assert "price_in_risk is a warning only" in " ".join(pkg["rules"])
    # no auto trading fields from price-in
    assert "trading_action" not in pkg
    assert pkg.get("research_rating") is None


def test_limit_up_bullish_is_high():
    assert (
        classify_price_in_risk(
            ret_since_event=0.02,
            abs_ret_1d=0.02,
            limit_up=True,
            limit_down=False,
            news_direction="BULLISH",
        )
        == "HIGH"
    )
