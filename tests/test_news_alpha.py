from __future__ import annotations

from ashare.research.news_alpha import build_news_alpha_attribution, news_alpha_bucket


def _outcome(sym: str, *, primary: str, sources: list[str], quant_top: bool = False) -> dict:
    return {
        "symbol": sym,
        "discovery_primary_source": primary,
        "candidate_sources": sources,
        "quant_top_n_at_signal": quant_top,
        "primary_horizons": {
            "5": {
                "actual_return": 0.03,
                "selection_alpha": 0.02,
                "market_alpha": 0.015,
            },
            "10": {
                "actual_return": 0.04,
                "selection_alpha": 0.025,
            },
        },
    }


def test_news_alpha_bucket_abcd():
    assert news_alpha_bucket(_outcome("A", primary="news", sources=["news"], quant_top=True)) == "A"
    assert news_alpha_bucket(_outcome("B", primary="news", sources=["news"], quant_top=False)) == "B"
    assert news_alpha_bucket(_outcome("C", primary="quant", sources=["quant"], quant_top=True)) == "C"
    assert news_alpha_bucket(_outcome("D", primary="event", sources=["event"], quant_top=False)) == "D"


def test_insufficient_sample_with_few_outcomes():
    outcomes = [_outcome("X", primary="news", sources=["news"])]
    pack = build_news_alpha_attribution(outcomes, {"research": {"attribution": {"minimum_sample_size": 30}}})
    h5 = pack["news_discovery_alpha"].get("5") or {}
    assert h5.get("status") == "INSUFFICIENT_SAMPLE"
    assert h5.get("sample_count", 0) < 30
