"""V5.4 Notification price truth separation."""

from __future__ import annotations

from ashare.research.price_truth import (
    ENTRY_NOTIFY,
    ENTRY_PAPER_FILL,
    ENTRY_SIGNAL,
    attach_paper_fill_price,
    attach_signal_price,
    paper_fill_price_from_outcome,
    signal_price_from_outcome,
)


def test_signal_price_explicit():
    o = attach_signal_price({}, 10.5)
    assert o["signal_price"] == 10.5
    assert o["entry_type_research"] == ENTRY_SIGNAL


def test_paper_fill_price_explicit():
    o = attach_paper_fill_price({}, 10.8)
    assert o["paper_fill_price"] == 10.8
    assert o["entry_type_paper"] == ENTRY_PAPER_FILL


def test_prices_not_mixed():
    o = {
        "signal_price": 10.0,
        "paper_fill_price": 10.2,
        "primary_horizons": {"5": {"actual_return": 0.05}},
    }
    assert signal_price_from_outcome(o) == 10.0
    assert paper_fill_price_from_outcome(o) == 10.2


def test_notification_entry_type():
    assert ENTRY_NOTIFY == "notify_price"
