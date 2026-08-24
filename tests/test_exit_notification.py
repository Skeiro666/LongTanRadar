from __future__ import annotations

from ashare.portfolio.exit.notify import maybe_build_alpha_exit_notification, persist_exit_signal
from ashare.portfolio.exit.quality import classify_exit_timing


def test_alpha_exit_threshold():
    assert maybe_build_alpha_exit_notification({"exit_score": 0.59, "action": "REDUCE"}, {"_root": "."}) is None
    n = maybe_build_alpha_exit_notification(
        {"symbol": "1", "exit_score": 0.61, "action": "REDUCE", "reasons": ["momentum_decay"]},
        {"_root": "."},
    )
    assert n["level"] == "ALPHA_EXIT"
    assert "metadata" in n


def test_persist_exit_signal(tmp_path):
    persist_exit_signal({"symbol": "x", "exit_score": 0.8, "action": "EXIT"}, {"_root": str(tmp_path)})
    path = tmp_path / "data" / "exit_signals.jsonl"
    assert path.exists()
    assert "EXIT" in path.read_text(encoding="utf-8")


def test_early_good_late():
    assert classify_exit_timing(exit_price=1, post_return_5d=0.05)["class"] == "EARLY"
    assert classify_exit_timing(exit_price=1, post_return_5d=-0.05)["class"] == "GOOD"
    assert classify_exit_timing(exit_price=1, post_return_5d=0.0, drawdown_at_exit=0.2)["class"] == "LATE"
