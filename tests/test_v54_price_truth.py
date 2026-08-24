"""V5.4 price truth separation."""

from __future__ import annotations

from ashare.research.price_truth import (
    attach_paper_fill_price,
    attach_signal_price,
    paper_fill_price_from_outcome,
    signal_price_from_outcome,
)


def test_signal_and_fill_prices_separate():
    o = {"signal_price": 10.0, "execution": {"fill_price": 10.5}}
    attach_signal_price(o, 10.0)
    attach_paper_fill_price(o, 10.5)
    assert signal_price_from_outcome(o) == 10.0
    assert paper_fill_price_from_outcome(o) == 10.5
    assert signal_price_from_outcome(o) != paper_fill_price_from_outcome(o)
