from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from ashare.config_loaders import load_yaml_config


def _forward_return(df: pd.DataFrame, as_of: pd.Timestamp, horizon: int) -> float | None:
    from ashare.asof import mask_on_or_before

    sub = df.copy()
    sub["date"] = pd.to_datetime(sub["date"])
    sub = sub.sort_values("date")
    hist = sub[mask_on_or_before(sub["date"], as_of)]
    fut = sub[~mask_on_or_before(sub["date"], as_of)]
    if hist.empty or len(fut) < horizon:
        return None
    entry = float(hist.iloc[-1]["close"])
    exit_px = float(fut.iloc[horizon - 1]["close"])
    if entry <= 0:
        return None
    return exit_px / entry - 1.0


def equal_weight_benchmark_returns(
    panel: dict[str, pd.DataFrame],
    as_of,
    horizons: list[int] | None = None,
) -> dict[str, Any]:
    """Cross-section equal-weight mean forward return — Selection benchmark."""
    horizons = [int(h) for h in (horizons or [1, 3, 5, 10, 20, 60])]
    as_of_ts = pd.Timestamp(str(as_of)[:10])
    by_h: dict[int, list[float]] = {h: [] for h in horizons}
    used = 0
    for df in panel.values():
        if df is None or df.empty:
            continue
        used += 1
        for h in horizons:
            r = _forward_return(df, as_of_ts, h)
            if r is not None:
                by_h[h].append(r)

    returns: dict[str, float | None] = {}
    for h in horizons:
        vals = by_h[h]
        returns[str(h)] = float(sum(vals) / len(vals)) if vals else None

    return {
        "method": "equal_weight_universe",
        "label": "Equal-weight Universe",
        "as_of": str(as_of_ts.date()),
        "n_symbols": used,
        "returns": returns,
        "benchmark_available": used > 0,
    }


def csi300_benchmark_returns(
    index_df: pd.DataFrame,
    as_of,
    horizons: list[int] | None = None,
) -> dict[str, Any]:
    """CSI300 (000300) index forward returns — Market benchmark."""
    horizons = [int(h) for h in (horizons or [1, 3, 5, 10, 20, 60])]
    as_of_ts = pd.Timestamp(str(as_of)[:10])
    if index_df is None or index_df.empty:
        return {
            "method": "csi300",
            "label": "CSI300",
            "index": "000300",
            "as_of": str(as_of_ts.date()),
            "returns": {str(h): None for h in horizons},
            "benchmark_available": False,
            "note": "csi300_index_unavailable",
        }
    returns: dict[str, float | None] = {}
    for h in horizons:
        returns[str(h)] = _forward_return(index_df, as_of_ts, h)
    wired = any(v is not None for v in returns.values())
    return {
        "method": "csi300",
        "label": "CSI300",
        "index": "000300",
        "as_of": str(as_of_ts.date()),
        "returns": returns,
        "benchmark_available": wired,
    }


def benchmark_snapshot(
    *,
    requested: str,
    actual: str,
    as_of: str,
    index: str | None = None,
    fallback: bool = False,
    fallback_reason: str | None = None,
    market: dict[str, Any] | None = None,
    universe: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """V5.2 canonical benchmark block for snapshots and research payload."""
    return {
        "requested": requested,
        "actual": actual,
        "index": index,
        "fallback": fallback,
        "fallback_reason": fallback_reason,
        "as_of": as_of,
        "market_benchmark": market,
        "universe_benchmark": universe,
    }


def resolve_dual_benchmark_pack(
    cfg: dict[str, Any],
    panel: dict[str, pd.DataFrame],
    as_of,
    horizons: list[int] | None = None,
) -> dict[str, Any]:
    """
    Resolve Market (CSI300) and Selection (equal-weight universe) benchmarks.
    Never conflate the two; expose fallback honestly in snapshot.
    """
    horizons = [int(h) for h in (horizons or [1, 3, 5, 10, 20, 60])]
    tracking = dict(load_yaml_config(cfg, "research").get("tracking") or {})
    requested = str(tracking.get("benchmark") or "csi300").lower()
    as_of_str = str(pd.Timestamp(str(as_of)[:10]).date())

    universe = equal_weight_benchmark_returns(panel, as_of, horizons=horizons)

    from ashare.data.akshare_source import fetch_csi300_index_bars

    idx = fetch_csi300_index_bars(cfg) if requested in {"csi300", "hs300", "000300"} else None
    market = csi300_benchmark_returns(idx, as_of, horizons=horizons) if idx is not None else csi300_benchmark_returns(
        pd.DataFrame(), as_of, horizons=horizons
    )

    if requested in {"csi300", "hs300", "000300"}:
        if market.get("benchmark_available"):
            snap = benchmark_snapshot(
                requested="csi300",
                actual="csi300",
                as_of=as_of_str,
                index="000300",
                fallback=False,
                fallback_reason=None,
                market=market,
                universe=universe,
            )
            primary = "csi300"
        else:
            snap = benchmark_snapshot(
                requested="csi300",
                actual="equal_weight_universe",
                as_of=as_of_str,
                index="000300",
                fallback=True,
                fallback_reason="csi300_unavailable",
                market=market,
                universe=universe,
            )
            primary = "equal_weight_universe"
    else:
        snap = benchmark_snapshot(
            requested="equal_weight_universe",
            actual="equal_weight_universe",
            as_of=as_of_str,
            index=None,
            fallback=False,
            fallback_reason=None,
            market=market if market.get("benchmark_available") else None,
            universe=universe,
        )
        primary = "equal_weight_universe"

    return {
        "snapshot": snap,
        "primary": primary,
        "market_returns": {k: v for k, v in (market.get("returns") or {}).items() if v is not None},
        "universe_returns": {k: v for k, v in (universe.get("returns") or {}).items() if v is not None},
        "market": market,
        "universe": universe,
        # legacy single-benchmark field for older callers
        "returns": (market.get("returns") if primary == "csi300" and market.get("benchmark_available") else universe.get("returns")),
        "method": primary,
        "benchmark_available": bool(
            (primary == "csi300" and market.get("benchmark_available"))
            or (primary == "equal_weight_universe" and universe.get("benchmark_available"))
        ),
        "fallback_from": snap.get("fallback_reason"),
    }


def resolve_benchmark_pack(
    cfg: dict[str, Any],
    panel: dict[str, pd.DataFrame],
    as_of,
    horizons: list[int] | None = None,
) -> dict[str, Any]:
    """Backward-compatible wrapper — prefer resolve_dual_benchmark_pack."""
    dual = resolve_dual_benchmark_pack(cfg, panel, as_of, horizons=horizons)
    pack = dict(dual.get("market") if dual.get("primary") == "csi300" else dual.get("universe") or {})
    pack["primary"] = dual.get("primary")
    pack["snapshot"] = dual.get("snapshot")
    pack["returns"] = dual.get("returns") or {}
    if dual.get("fallback_from"):
        pack["fallback_from"] = dual["fallback_from"]
    return pack


def _schedule_path(cfg: dict[str, Any]) -> Path:
    root = Path(cfg.get("_root") or Path(__file__).resolve().parents[2])
    return root / "data" / "cache" / "roundtable_schedule.json"


def should_run_roundtable(cfg: dict[str, Any], *, as_of: date | None = None) -> tuple[bool, str]:
    """
    V5.2 roundtable scheduling — benchmark path only, never controls trading.
    Modes: disabled | benchmark (every run) | sampled | scheduled
    """
    ai = dict(cfg.get("ai") or {})
    if not bool(ai.get("roundtable", True)):
        return False, "roundtable_disabled"
    mode = str(ai.get("roundtable_mode") or "sampled").lower()
    if mode == "disabled":
        return False, "mode_disabled"
    if mode == "benchmark":
        return True, "mode_benchmark_every_run"

    today = (as_of or date.today()).isoformat()
    path = _schedule_path(cfg)
    state: dict[str, Any] = {"run_count": 0, "last_run_date": None}
    if path.is_file():
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pass

    run_count = int(state.get("run_count") or 0) + 1
    state["run_count"] = run_count

    if mode == "scheduled":
        max_per_day = int(ai.get("roundtable_max_per_day") or 1)
        last = state.get("last_run_date")
        if last == today and int(state.get("runs_today") or 0) >= max_per_day:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
            return False, f"scheduled_daily_cap_{max_per_day}"
        if last != today:
            state["runs_today"] = 0
        state["runs_today"] = int(state.get("runs_today") or 0) + 1
        state["last_run_date"] = today
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        return True, "scheduled_daily_run"

    if mode == "sampled":
        every = max(1, int(ai.get("roundtable_sample_every") or 10))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        if run_count % every == 0:
            return True, f"sampled_every_{every}_run_{run_count}"
        return False, f"sampled_skip_run_{run_count}_every_{every}"

    return True, f"unknown_mode_{mode}_default_run"
