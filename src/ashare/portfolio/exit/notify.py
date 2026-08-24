from __future__ import annotations

"""ALPHA_EXIT notification helpers — does not replace RISK/RATING_EXIT."""

from typing import Any

from ashare.config_loaders import load_yaml_config
from ashare.portfolio.exit.config import load_exit_config

NOTIFY_LEVEL_ALPHA_EXIT = "ALPHA_EXIT"


def maybe_build_alpha_exit_notification(signal: dict[str, Any], cfg: dict[str, Any] | None = None) -> dict[str, Any] | None:
    exit_cfg = load_exit_config(cfg)
    ncfg = dict(exit_cfg.get("notification") or {})
    if not ncfg.get("alpha_exit_enabled", True):
        return None
    thr = float(ncfg.get("exit_score_threshold", 0.60))
    score = float(signal.get("exit_score") or 0)
    action = str(signal.get("action") or "HOLD")
    if score < thr or action not in {"REDUCE", "EXIT"}:
        return None

    return {
        "level": NOTIFY_LEVEL_ALPHA_EXIT,
        "symbol": signal.get("symbol"),
        "price": signal.get("current_price"),
        "exit_score": score,
        "action": action,
        "expected_return_5d": signal.get("expected_return_5d"),
        "expected_return_10d": signal.get("expected_return_10d"),
        "expected_return": signal.get("expected_return_10d") or signal.get("expected_return_5d"),
        "reasons": (signal.get("reason_texts") or signal.get("reasons") or [])[:3],
        "top_3_exit_reasons": (signal.get("reason_texts") or signal.get("reasons") or [])[:3],
        "exit_types": signal.get("exit_types"),
        "current_price": signal.get("current_price"),
        "hold_score": signal.get("hold_score"),
        "confidence": signal.get("confidence"),
        "signal_time": signal.get("signal_time"),
        "versions": signal.get("versions"),
        "metadata": {
            "exit_score": score,
            "action": action,
            "price": signal.get("current_price"),
            "reasons": (signal.get("reasons") or [])[:3],
            "expected_return_5d": signal.get("expected_return_5d"),
            "expected_return_10d": signal.get("expected_return_10d"),
            "model_version": (signal.get("versions") or {}).get("model_version"),
            "factor_version": (signal.get("versions") or {}).get("factor_version"),
            "exit_version": (signal.get("versions") or {}).get("exit_version"),
            "news_version": (signal.get("versions") or {}).get("news_version"),
            "change_reason": "alpha_exit",
        },
    }


def persist_exit_signal(signal: dict[str, Any], cfg: dict[str, Any] | None = None) -> None:
    """Append exit signal for outcome replay."""
    from pathlib import Path
    import json
    from datetime import datetime, timezone

    root = Path((cfg or {}).get("_root") or Path(__file__).resolve().parents[3])
    path = root / "data" / "exit_signals.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        **signal,
        "persisted_at": datetime.now(timezone.utc).isoformat(),
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
