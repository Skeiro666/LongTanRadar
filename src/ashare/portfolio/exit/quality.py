from __future__ import annotations

"""Exit timing quality: EARLY / GOOD / LATE — config thresholds + MFE/MAE."""

from typing import Any


def classify_exit_timing(
    *,
    exit_price: float | None,
    peak_before_exit: float | None = None,
    post_return_1d: float | None = None,
    post_return_5d: float | None = None,
    post_return_10d: float | None = None,
    drawdown_at_exit: float | None = None,
    mae: float | None = None,
    early_threshold: float = 0.03,
    good_threshold: float = -0.02,
    late_drawdown: float = 0.12,
    late_mae: float = 0.10,
) -> dict[str, Any]:
    """
    GOOD: post-exit returns clearly negative (caught a top-ish exit).
    EARLY: post-exit returns clearly positive (left money on table).
    LATE: large drawdown from peak / adverse excursion before exit.
    Thresholds come from config/exit.yaml timing_quality.
    """
    if exit_price is None and post_return_5d is None and post_return_10d is None and post_return_1d is None:
        return {"available": False, "class": "UNKNOWN", "note": "missing_post_exit_returns"}

    post = post_return_5d if post_return_5d is not None else post_return_10d
    if post is None:
        post = post_return_1d
    if post is None:
        return {"available": False, "class": "UNKNOWN", "note": "missing_post_exit_returns"}

    # Late: already large drawdown from peak OR deep MAE when exiting
    if drawdown_at_exit is not None and drawdown_at_exit >= late_drawdown:
        return {
            "available": True,
            "class": "LATE",
            "post_return_1d": post_return_1d,
            "post_return_5d": post_return_5d,
            "post_return_10d": post_return_10d,
            "drawdown_at_exit": drawdown_at_exit,
            "mae": mae,
            "peak_before_exit": peak_before_exit,
            "note": "large_drawdown_before_exit",
        }
    if mae is not None and mae <= -abs(late_mae):
        return {
            "available": True,
            "class": "LATE",
            "post_return_1d": post_return_1d,
            "post_return_5d": post_return_5d,
            "post_return_10d": post_return_10d,
            "drawdown_at_exit": drawdown_at_exit,
            "mae": mae,
            "peak_before_exit": peak_before_exit,
            "note": "deep_mae_before_exit",
        }

    if post >= early_threshold:
        cls = "EARLY"
        note = "price_continued_up_after_exit"
    elif post <= good_threshold:
        cls = "GOOD"
        note = "price_fell_after_exit"
    else:
        cls = "GOOD" if post < 0 else "EARLY"
        note = "borderline"

    return {
        "available": True,
        "class": cls,
        "post_return_1d": post_return_1d,
        "post_return_5d": post_return_5d,
        "post_return_10d": post_return_10d,
        "drawdown_at_exit": drawdown_at_exit,
        "mae": mae,
        "peak_before_exit": peak_before_exit,
        "note": note,
        "thresholds": {
            "early_post_return": early_threshold,
            "good_post_return": good_threshold,
            "late_drawdown": late_drawdown,
            "late_mae": late_mae,
        },
    }


def summarize_exit_quality(rows: list[dict[str, Any]], *, minimum_sample: int = 30) -> dict[str, Any]:
    classes = [r.get("class") for r in rows if r.get("available") and r.get("class") in {"EARLY", "GOOD", "LATE"}]
    n = len(classes)
    if n < minimum_sample:
        return {
            "available": False,
            "status": "INSUFFICIENT_SAMPLE",
            "sample_count": n,
            "minimum_sample": minimum_sample,
            "early_pct": None,
            "good_pct": None,
            "late_pct": None,
        }
    return {
        "available": True,
        "sample_count": n,
        "early_pct": round(classes.count("EARLY") / n, 4),
        "good_pct": round(classes.count("GOOD") / n, 4),
        "late_pct": round(classes.count("LATE") / n, 4),
        "status": "OK",
    }
