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
from ashare.portfolio.exit.calibration import calibrate_exit_scores
from ashare.portfolio.exit.ml_exit import train_exit_ml
from ashare.symbols import to_symbol

logger = logging.getLogger("ashare.services.exit")


def _root(cfg: dict[str, Any]) -> Path:
    return Path(cfg.get("_root") or Path(__file__).resolve().parents[2])


def _load_bars_for_symbol(cfg: dict[str, Any], symbol: str, lookback: int = 120) -> pd.DataFrame:
    try:
        from ashare.data.provider import ensure_panel

        panel = ensure_panel(cfg)
        if panel is None or panel.empty:
            return pd.DataFrame()
        sym = to_symbol(symbol)
        df = panel[panel["symbol"].astype(str).map(to_symbol) == sym].copy()
        if df.empty:
            # try raw symbol
            df = panel[panel["symbol"] == symbol].copy()
        if df.empty:
            return pd.DataFrame()
        df = df.sort_values("date").tail(lookback)
        return df
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
            # enrich from ledger meta if present
            meta = _position_meta(cfg, sym)
            entry_date = meta.get("entry_date")
            peak = float(meta.get("max_favorable_price") or mark)
            if mark > peak:
                peak = mark
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
    # scan trades for first BUY
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

    # portfolio weights
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

    # merge position + signal for UI
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

    # price series for charts (last 60)
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
        }

    return {
        "as_of": as_of,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "positions": enriched,
        "counts": pack.get("counts"),
        "charts": charts,
        "alpha_exit_notifications": notifications,
        "note": "Exit signals only — does not auto-sell. Paper/live execution unchanged.",
    }


def _append_alpha_exit_store(cfg: dict[str, Any], note: dict[str, Any]) -> None:
    path = _root(cfg) / "data" / "notifications" / "alpha_exit.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(note, ensure_ascii=False, default=str) + "\n")


def build_exit_lab(cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """Exit performance dashboard payload for Alpha Lab."""
    cfg = cfg or {}
    exit_cfg = load_exit_config(cfg)
    min_n = int(exit_cfg.get("minimum_sample") or 30)

    # Build synthetic entries from exit_signals + paper trades if any
    entries, bars_by, cal_rows = _historical_entries(cfg)
    alpha = build_exit_alpha(bars_by, entries, cfg=cfg) if entries else {
        "available": False,
        "minimum_sample": min_n,
        "strategies": [],
        "note": "INSUFFICIENT_SAMPLE — no historical entries",
    }
    calibration = calibrate_exit_scores(cal_rows, bars_by, cfg=cfg) if cal_rows else {
        "buckets": [],
        "status": "INSUFFICIENT_SAMPLE",
    }

    # ML train attempt (no-op if insufficient)
    ml_result = {"available": False, "status": "INSUFFICIENT_SAMPLE", "sample_count": 0}
    samples = _ml_samples_from_entries(cfg, entries, bars_by)
    if samples:
        ml_result = train_exit_ml(samples, cfg=cfg)

    return {
        "exit_alpha": alpha,
        "calibration": calibration,
        "ml": ml_result,
        "minimum_sample": min_n,
        "n_entries": len(entries),
    }


def _historical_entries(cfg: dict[str, Any]) -> tuple[list[dict], dict[str, pd.DataFrame], list[dict]]:
    root = _root(cfg)
    entries: list[dict] = []
    cal_rows: list[dict] = []
    # from paper trades
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
                    }
                )
        except Exception:  # noqa: BLE001
            pass
    # from exit signals for calibration
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
                }
            )

    # dedupe entries
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
