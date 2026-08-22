"""Research progress tracker."""

from __future__ import annotations

from ashare.research.progress import get_research_progress


def test_progress_step_and_timing():
    p = get_research_progress()
    p.reset()
    with p.step("pool", "test pool", note="unit"):
        p.log("pool", "detail msg")
    snap = p.snapshot()
    assert snap["steps"]
    assert snap["pipeline_timing"][0]["phase"] == "pool"
    assert snap["pipeline_timing"][0]["status"] == "done"
