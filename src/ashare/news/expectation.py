from __future__ import annotations

from typing import Any


def expectation_gap(*, actual: float | None = None, consensus: float | None = None) -> dict[str, Any]:
    """Never invent market consensus. If missing, mark unavailable."""
    if consensus is None or actual is None:
        return {
            "available": False,
            "gap": None,
            "label": "unknown",
            "confidence": 0.0,
            "note": "无一致预期数据，禁止假装知道市场预期",
        }
    raw = float(actual) - float(consensus)
    # squash to [-1,1] assuming percent points around 0.2
    gap = max(-1.0, min(1.0, raw / 0.2))
    if gap > 0.15:
        label = "positive_surprise"
    elif gap < -0.15:
        label = "negative_surprise"
    else:
        label = "in_line"
    return {"available": True, "gap": gap, "label": label, "confidence": 0.6, "note": ""}
