"""Exit service — evaluate paper book, persist signals, feed UI/API. No live broker."""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from ashare.portfolio.exit.engine import ExitEngine, evaluate_book
from ashare.portfolio.exit.notify import maybe_build_alpha_exit_notification, persist_exit_signal
from ashare.portfolio.exit.config import load_exit_config
from ashare.portfolio.exit.alpha import build_exit_alpha
from ashare.portfolio.exit.calibration import calibrate_exit_scores, feature_ic_table, feature_redundancy
from ashare.portfolio.exit.ml_exit import train_exit_ml, compare_ml_vs_heuristic
from ashare.portfolio.exit.report import build_exit_validation_report
from ashare.portfolio.exit.research_bootstrap import bootstrap_research_entries
from ashare.symbols import to_symbol

logger = logging.getLogger("ashare.services.exit")


def _root(cfg: dict[str, Any]) -> Path:
    return Path(cfg.get("_root") or Path(__file__).resolve().parents[2])


def _load_bars_for_symbol(cfg: dict[str, Any], symbol: str, lookback: int = 120) -> pd.DataFrame:
    try:
        from ashare.data.provider import ensure_panel

        panel = ensure_panel(cfg, [symbol])
        if not isinstance(panel, dict) or not panel:
            return pd.DataFrame()
        sym = to_symbol(symbol)
        df = panel.get(sym) or panel.get(symbol)
        if df is None or getattr(df, "empty", True):
            # try any key match
            for k, v in panel.items():
                if to_symbol(str(k)) == sym:
                    df = v
                    break
        if df is None or getattr(df, "empty", True):
            return pd.DataFrame()
        return df.sort_values("date").tail(lookback).copy()
    except Exception as exc:  # noqa: BLE001
        logger.debug("bars load failed %s: %s", symbol, exc)
        return pd.DataFrame()


def _paper_position_rows(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    try:
        from ashare.services.trading import build_live_or_paper

        broker = build_live_or_paper(cfg)
        broker.connect()
        marks = {}
        try:
            from ashare.data.provider import latest_marks

            marks = latest_marks(cfg) or {}
        except Exception:  # noqa: BLE001
            marks = {}
        rows = []
        for p in broker.get_positions():
            shares = int(getattr(p, "shares", 0) or getattr(p, "quantity", 0) or 0)
            if shares <= 0:
                continue
            sym = to_symbol(p.symbol)
            mark = float(marks.get(sym) or marks.get(p.symbol) or p.cost_price or 0)
            meta = _position_meta(cfg, sym)
            entry_date = meta.get("entry_date")
            peak = float(meta.get("max_favorable_price") or mark)
            trough = float(meta.get("max_adverse_price") or mark)
            if mark > peak:
                peak = mark
            if mark < trough:
                trough = mark
            rows.append(
                {
                    "symbol": sym,
                    "name": meta.get("name"),
                    "shares": shares,
                    "available": int(getattr(p, "available", shares) or shares),
                    "cost_price": float(p.cost_price or 0),
                    "entry_price": float(meta.get("entry_price") or p.cost_price or 0),
                    "entry_date": entry_date,
                    "current_price": mark,
                    "max_favorable_price": peak,
                    "max_adverse_price": trough,
                    "market_value": mark * shares,
                    "unrealized_return": (mark / float(p.cost_price) - 1.0) if p.cost_price else None,
                }
            )
        return rows
    except Exception as exc:  # noqa: BLE001
        logger.warning("paper positions failed: %s", exc)
        return []


def _position_meta(cfg: dict[str, Any], symbol: str) -> dict[str, Any]:
    path = _root(cfg) / "data" / "position_meta.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return dict((data.get("positions") or {}).get(to_symbol(symbol)) or {})
    except Exception:  # noqa: BLE001
        return {}


def update_position_meta_from_fills(cfg: dict[str, Any]) -> None:
    """Best-effort: set entry_date / peak from paper ledger trades."""
    path = _root(cfg) / "data" / "paper_state.json"
    meta_path = _root(cfg) / "data" / "position_meta.json"
    if not path.exists():
        return
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return
    meta = {"positions": {}}
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            meta = {"positions": {}}
    positions = {to_symbol(p["symbol"]): p for p in (state.get("positions") or [])}
    for t in state.get("trades") or []:
        if str(t.get("side") or "").upper() != "BUY":
            continue
        sym = to_symbol(t.get("symbol") or "")
        if sym not in positions:
            continue
        cur = dict((meta.get("positions") or {}).get(sym) or {})
        if not cur.get("entry_date"):
            cur["entry_date"] = str(t.get("timestamp") or "")[:10]
            cur["entry_price"] = float(t.get("price") or positions[sym].get("cost_price") or 0)
        meta.setdefault("positions", {})[sym] = cur
    for sym, p in positions.items():
        cur = dict((meta.get("positions") or {}).get(sym) or {})
        cur.setdefault("entry_price", float(p.get("cost_price") or 0))
        meta.setdefault("positions", {})[sym] = cur
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def evaluate_exit_book(cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = cfg or {}
    update_position_meta_from_fills(cfg)
    positions = _paper_position_rows(cfg)
    bars_by: dict[str, pd.DataFrame] = {}
    for p in positions:
        bars_by[p["symbol"]] = _load_bars_for_symbol(cfg, p["symbol"])

    equity = sum(float(p.get("market_value") or 0) for p in positions) or 1.0
    ctx = {}
    for p in positions:
        w = float(p.get("market_value") or 0) / equity
        meta = _position_meta(cfg, p["symbol"])
        ctx[p["symbol"]] = {
            "portfolio": {"weight": w},
            "buy_thesis": meta.get("buy_thesis"),
            "event": meta.get("event") or {"event_state": meta.get("event_state", "UNKNOWN")},
            "news": meta.get("news") or {},
        }

    as_of = date.today().isoformat()
    pack = evaluate_book(positions, bars_by_symbol=bars_by, cfg=cfg, as_of=as_of, context_by_symbol=ctx)

    by_sym = {r["symbol"]: r for r in pack.get("signals") or []}
    enriched = []
    notifications = []
    for p in positions:
        sig = by_sym.get(p["symbol"]) or {}
        row = {**p, "exit": sig}
        enriched.append(row)
        if sig.get("available"):
            persist_exit_signal(sig, cfg)
            note = maybe_build_alpha_exit_notification(sig, cfg)
            if note:
                notifications.append(note)
                _append_alpha_exit_store(cfg, note)

    charts = {}
    for sym, df in bars_by.items():
        if df is None or df.empty:
            continue
        d2 = df.tail(60).copy()
        d2["date"] = pd.to_datetime(d2["date"]).dt.strftime("%Y-%m-%d")
        close = d2["close"].astype(float)
        ma20 = close.rolling(20).mean()
        charts[sym] = {
            "dates": d2["date"].tolist(),
            "price": close.round(4).tolist(),
            "ma20": [None if pd.isna(x) else round(float(x), 4) for x in ma20],
            "entry": (by_sym.get(sym) or {}).get("entry_price") or None,
            "exit_action": (by_sym.get(sym) or {}).get("action"),
            "exit_score": (by_sym.get(sym) or {}).get("exit_score"),
            "hold_score": (by_sym.get(sym) or {}).get("hold_score"),
        }

    return {
        "as_of": as_of,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "positions": enriched,
        "counts": pack.get("counts"),
        "charts": charts,
        "alpha_exit_notifications": notifications,
        "hold_score_formula": "1 - exit_score",
        "note": "Exit signals only — does not auto-sell. Paper/live execution unchanged.",
    }


def _append_alpha_exit_store(cfg: dict[str, Any], note: dict[str, Any]) -> None:
    path = _root(cfg) / "data" / "notifications" / "alpha_exit.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(note, ensure_ascii=False, default=str) + "\n")


def build_exit_lab(cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """Exit Validation payload for Alpha Lab — research only."""
    cfg = cfg or {}
    exit_cfg = load_exit_config(cfg)
    min_n = int(exit_cfg.get("minimum_sample") or 30)

    entries, bars_by, cal_rows = _historical_entries(cfg)
    # Research bootstrap when paper history thin
    boot_cfg = dict((exit_cfg.get("backtest") or {}).get("research_bootstrap") or {})
    if boot_cfg.get("enabled", True) and len(entries) < min_n:
        try:
            from ashare.data.provider import ensure_panel

            panel = ensure_panel(cfg)
            boot_entries, boot_bars = bootstrap_research_entries(
                panel,
                max_symbols=int(boot_cfg.get("max_symbols", 40)),
                entries_per_symbol=int(boot_cfg.get("entries_per_symbol", 3)),
                min_bars_before_entry=int(boot_cfg.get("min_bars_before_entry", 40)),
                step_days=int(boot_cfg.get("step_days", 15)),
            )
            # merge without overwriting paper entries
            seen = {(e.get("symbol"), e.get("entry_date")) for e in entries}
            for e in boot_entries:
                key = (e.get("symbol"), e.get("entry_date"))
                if key in seen:
                    continue
                entries.append(e)
                seen.add(key)
            for sym, df in boot_bars.items():
                if sym not in bars_by:
                    bars_by[sym] = df
            # calibration rows from bootstrap mid-hold scores
            cal_rows = cal_rows + _calibration_rows_from_entries(cfg, entries, bars_by)
        except Exception as exc:  # noqa: BLE001
            logger.warning("research bootstrap failed: %s", exc)

    alpha = (
        build_exit_alpha(bars_by, entries, cfg=cfg)
        if entries
        else {
            "available": False,
            "minimum_sample": min_n,
            "strategies": [],
            "note": "INSUFFICIENT_SAMPLE — no historical entries",
        }
    )
    calibration = (
        calibrate_exit_scores(cal_rows, bars_by, cfg=cfg)
        if cal_rows
        else {
            "buckets": [],
            "status": "INSUFFICIENT_SAMPLE",
            "available": False,
            "sample_count": 0,
            "scatter_t10": [],
            "ic": {},
            "monotonicity": "INSUFFICIENT_SAMPLE",
        }
    )
    feat_ic = feature_ic_table(cal_rows, bars_by, cfg=cfg) if cal_rows else {
        "features": [],
        "status": "INSUFFICIENT_SAMPLE",
        "available": False,
    }
    redundancy = feature_redundancy(cal_rows, cfg=cfg) if cal_rows else {
        "pairs": [],
        "status": "INSUFFICIENT_SAMPLE",
        "available": False,
        "feature_groups": exit_cfg.get("feature_groups") or {},
    }

    samples = _ml_samples_from_entries(cfg, entries, bars_by)
    ml_cmp = compare_ml_vs_heuristic(samples, cfg=cfg) if samples else {
        "available": False,
        "status": "INSUFFICIENT_SAMPLE",
        "keep": "HEURISTIC",
    }
    ml_result = train_exit_ml(samples, cfg=cfg) if samples else {
        "available": False,
        "status": "INSUFFICIENT_SAMPLE",
        "sample_count": 0,
        "trained": False,
        "keep": "HEURISTIC",
    }

    pack = {
        "exit_alpha": alpha,
        "calibration": calibration,
        "feature_ic": feat_ic,
        "redundancy": redundancy,
        "ml": ml_result,
        "ml_vs_heuristic": ml_cmp,
        "minimum_sample": min_n,
        "n_entries": len(entries),
        "n_calibration_rows": len(cal_rows),
        "execution_model": "t1_open",
        "hold_score_formula": exit_cfg.get("hold_score_formula") or "1 - exit_score",
        "versions": {
            "exit_version": exit_cfg.get("version"),
            "as_of": date.today().isoformat(),
        },
    }
    # leakage suite is unit-tested separately; surface status if previously run artifact exists
    leak_path = _root(cfg) / "data" / "exit_leakage_last.json"
    if leak_path.exists():
        try:
            pack["leakage_tests"] = json.loads(leak_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pack["leakage_tests"] = {"passed": None}
    else:
        pack["leakage_tests"] = {"passed": None, "note": "run pytest test_exit_leakage"}

    pack["validation_report"] = build_exit_validation_report(pack)
    pack["exit_validation"] = {
        "calibration": calibration,
        "feature_ic": feat_ic,
        "redundancy": redundancy,
        "ablation": alpha.get("strategies"),
        "timing": (alpha.get("backtest") or {}).get("strategies", {}).get("exit_engine", {}).get("exit_quality"),
        "giveback": {
            "no_exit": _gb(alpha, "no_exit"),
            "fixed_stop": _gb(alpha, "fixed_stop"),
            "exit_engine": _gb(alpha, "exit_engine"),
        },
        "charts": {
            "scatter_t10": calibration.get("scatter_t10") or [],
            "bucket_t10": [
                {"range": b.get("range"), "t10_mean": b.get("t10_mean"), "status": b.get("status")}
                for b in (calibration.get("buckets") or [])
            ],
            "bucket_loss_rate": [
                {"range": b.get("range"), "loss_rate": b.get("t10_loss_rate"), "status": b.get("status")}
                for b in (calibration.get("buckets") or [])
            ],
            "available": bool(calibration.get("available")),
        },
        "report": pack["validation_report"],
    }
    return pack


def _gb(alpha: dict[str, Any], key: str) -> dict[str, Any]:
    for s in alpha.get("strategies") or []:
        if s.get("id") == key:
            return {
                "mean": s.get("mean_giveback"),
                "median": s.get("median_giveback"),
                "p90": s.get("p90_giveback"),
                "status": s.get("status"),
            }
    return {"status": "INSUFFICIENT_SAMPLE"}


def _historical_entries(cfg: dict[str, Any]) -> tuple[list[dict], dict[str, pd.DataFrame], list[dict]]:
    root = _root(cfg)
    entries: list[dict] = []
    cal_rows: list[dict] = []
    paper = root / "data" / "paper_state.json"
    if paper.exists():
        try:
            state = json.loads(paper.read_text(encoding="utf-8"))
            for t in state.get("trades") or []:
                if str(t.get("side") or "").upper() != "BUY":
                    continue
                entries.append(
                    {
                        "symbol": to_symbol(t.get("symbol")),
                        "entry_date": str(t.get("timestamp") or "")[:10],
                        "entry_price": float(t.get("price") or 0) or None,
                        "source": "paper",
                    }
                )
        except Exception:  # noqa: BLE001
            pass
    sig_path = root / "data" / "exit_signals.jsonl"
    if sig_path.exists():
        for line in sig_path.read_text(encoding="utf-8").splitlines()[-500:]:
            try:
                row = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            if row.get("exit_score") is None:
                continue
            cal_rows.append(
                {
                    "symbol": row.get("symbol"),
                    "signal_date": (row.get("as_of") or row.get("signal_time") or "")[:10],
                    "exit_score": row.get("exit_score"),
                    "exit_price": row.get("current_price"),
                    "features": row.get("features"),
                }
            )

    seen = set()
    uniq = []
    for e in entries:
        key = (e.get("symbol"), e.get("entry_date"))
        if not e.get("entry_date") or key in seen:
            continue
        seen.add(key)
        uniq.append(e)

    bars_by: dict[str, pd.DataFrame] = {}
    for e in uniq[:80]:
        sym = e["symbol"]
        if sym not in bars_by:
            bars_by[sym] = _load_bars_for_symbol(cfg, sym, lookback=250)
    for r in cal_rows[:80]:
        sym = str(r.get("symbol") or "")
        if sym and sym not in bars_by:
            bars_by[sym] = _load_bars_for_symbol(cfg, sym, lookback=250)
    return uniq, bars_by, cal_rows


def _calibration_rows_from_entries(
    cfg: dict[str, Any],
    entries: list[dict],
    bars_by: dict[str, pd.DataFrame],
) -> list[dict]:
    """Evaluate exit_score at mid-hold for calibration (as_of safe)."""
    from ashare.portfolio.exit.engine import ExitEngine

    engine = ExitEngine(cfg)
    rows = []
    for e in entries[:120]:
        sym = e["symbol"]
        bars = bars_by.get(sym)
        if bars is None or bars.empty:
            continue
        df = bars.copy()
        df["date"] = pd.to_datetime(df["date"]).dt.date
        df = df.sort_values("date").reset_index(drop=True)
        try:
            ed = pd.Timestamp(e["entry_date"]).date()
        except Exception:  # noqa: BLE001
            continue
        idxs = df.index[df["date"] >= ed]
        if len(idxs) <= 5:
            continue
        i = int(idxs[0]) + 5
        if i >= len(df) - 25:
            continue
        as_of = df.loc[i, "date"]
        hist = df.iloc[: i + 1]
        peak = float(hist["high"].max()) if "high" in hist.columns else float(hist["close"].max())
        sig = engine.evaluate(
            symbol=sym,
            bars=hist,
            as_of=as_of,
            position={
                "symbol": sym,
                "entry_price": e.get("entry_price") or float(df.loc[int(idxs[0]), "close"]),
                "entry_date": e["entry_date"],
                "max_favorable_price": peak,
                "current_price": float(df.loc[i, "close"]),
            },
        )
        if not sig.get("available"):
            continue
        rows.append(
            {
                "symbol": sym,
                "signal_date": str(as_of),
                "exit_score": sig.get("exit_score"),
                "exit_price": sig.get("current_price"),
                "features": sig.get("features"),
                "source": "research_bootstrap",
            }
        )
    return rows


def _ml_samples_from_entries(cfg, entries, bars_by) -> list[dict]:
    from ashare.portfolio.exit.features import compute_exit_features
    from ashare.portfolio.exit.labels import forward_returns

    samples = []
    engine_asof_offset = 5
    for e in entries:
        sym = e["symbol"]
        bars = bars_by.get(sym)
        if bars is None or bars.empty:
            continue
        df = bars.copy()
        df["date"] = pd.to_datetime(df["date"]).dt.date
        df = df.sort_values("date").reset_index(drop=True)
        try:
            ed = pd.Timestamp(e["entry_date"]).date()
        except Exception:  # noqa: BLE001
            continue
        idxs = df.index[df["date"] >= ed]
        if len(idxs) <= engine_asof_offset:
            continue
        i = int(idxs[0]) + engine_asof_offset
        if i >= len(df):
            continue
        as_of = df.loc[i, "date"]
        hist = df.iloc[: i + 1]
        feat = compute_exit_features(
            bars=hist,
            as_of=as_of,
            position={"symbol": sym, "entry_price": e.get("entry_price"), "entry_date": e["entry_date"]},
            cfg=cfg,
        )
        fr = forward_returns(df, signal_date=as_of, horizons=[10])
        if not (fr.get("10") or {}).get("available"):
            continue
        samples.append({"features": feat, "label_forward_return_10d": fr["10"]["return"]})
    return samples
