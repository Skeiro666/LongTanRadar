from __future__ import annotations

"""Exit validation: calibration, IC, redundancy, monotonicity. Research only."""

from typing import Any

import numpy as np
import pandas as pd

from ashare.portfolio.exit.config import load_exit_config
from ashare.portfolio.exit.labels import forward_returns

_BUCKETS = [(0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.01)]


def _corr(x: list[float], y: list[float], method: str = "spearman") -> float | None:
    if len(x) < 3 or len(y) < 3 or len(x) != len(y):
        return None
    a, b = pd.Series(x), pd.Series(y)
    if a.std() == 0 or b.std() == 0:
        return None
    if method == "pearson":
        return float(a.corr(b, method="pearson"))
    return float(a.corr(b, method="spearman"))


def _mdd_of_path(prices: list[float]) -> float | None:
    if len(prices) < 2:
        return None
    s = pd.Series(prices)
    peak = s.cummax()
    return float((s / peak - 1.0).min())


def calibrate_exit_scores(
    rows: list[dict[str, Any]],
    bars_by_symbol: dict,
    *,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    rows: [{symbol, signal_date, exit_score, exit_price?, features?}]
    Full calibration: T+1/5/10/20, loss/gain rates, MDD, IC, monotonicity.
    """
    exit_cfg = load_exit_config(cfg)
    vcfg = dict(exit_cfg.get("validation") or {})
    min_n = int(vcfg.get("minimum_sample") or exit_cfg.get("minimum_sample") or 30)
    bucket_min = int(vcfg.get("bucket_minimum_sample") or max(5, min_n // 3))
    horizons = list(vcfg.get("calibration_horizons") or [1, 5, 10, 20])

    # Collect paired score × forward returns
    pairs: list[dict[str, Any]] = []
    for r in rows:
        if r.get("exit_score") is None:
            continue
        bars = bars_by_symbol.get(str(r.get("symbol")))
        if bars is None or (hasattr(bars, "empty") and bars.empty):
            continue
        fr = forward_returns(
            bars,
            signal_date=r.get("signal_date"),
            horizons=horizons,
            base_mode="signal_close",
            price_field="close",
            adj_type="qfq",
        )
        item = {
            "exit_score": float(r["exit_score"]),
            "features": r.get("features") or {},
            "symbol": r.get("symbol"),
            "signal_date": r.get("signal_date"),
        }
        ok_any = False
        for h in horizons:
            cell = fr.get(str(h)) or {}
            if cell.get("available") and cell.get("return") is not None:
                item[f"r{h}"] = float(cell["return"])
                ok_any = True
            else:
                item[f"r{h}"] = None
        # path MDD over next 10 bars if possible
        try:
            df = bars.copy()
            df["date"] = pd.to_datetime(df["date"]).dt.date
            df = df.sort_values("date")
            sd = pd.Timestamp(r.get("signal_date")).date()
            sub = df[df["date"] >= sd].head(11)
            if len(sub) >= 2:
                item["fwd_mdd_10"] = _mdd_of_path(sub["close"].astype(float).tolist())
            else:
                item["fwd_mdd_10"] = None
        except Exception:  # noqa: BLE001
            item["fwd_mdd_10"] = None
        if ok_any:
            pairs.append(item)

    n_total = len(pairs)
    buckets_out = []
    means_t10: list[float] = []
    for lo, hi in _BUCKETS:
        subset = [p for p in pairs if lo <= p["exit_score"] < hi]
        cell: dict[str, Any] = {
            "range": f"{lo:.1f}-{hi:.1f}",
            "sample_count": len(subset),
        }
        if len(subset) < bucket_min:
            cell["status"] = "INSUFFICIENT_SAMPLE"
            for h in horizons:
                cell[f"t{h}_mean"] = None
                cell[f"t{h}_loss_rate"] = None
                cell[f"t{h}_gain_rate"] = None
            cell["max_drawdown_mean"] = None
        else:
            cell["status"] = "OK"
            for h in horizons:
                vals = [p[f"r{h}"] for p in subset if p.get(f"r{h}") is not None]
                if len(vals) < bucket_min:
                    cell[f"t{h}_mean"] = None
                    cell[f"t{h}_loss_rate"] = None
                    cell[f"t{h}_gain_rate"] = None
                else:
                    s = pd.Series(vals)
                    cell[f"t{h}_mean"] = float(s.mean())
                    cell[f"t{h}_loss_rate"] = float((s < 0).mean())
                    cell[f"t{h}_gain_rate"] = float((s > 0).mean())
            mdds = [p["fwd_mdd_10"] for p in subset if p.get("fwd_mdd_10") is not None]
            cell["max_drawdown_mean"] = float(np.mean(mdds)) if mdds else None
            if cell.get("t10_mean") is not None:
                means_t10.append(float(cell["t10_mean"]))
        buckets_out.append(cell)

    mono = False
    mono_status = "INSUFFICIENT_SAMPLE"
    if len(means_t10) >= 3:
        mono = all(means_t10[i] >= means_t10[i + 1] for i in range(len(means_t10) - 1))
        mono_status = "TRUE" if mono else "FALSE"
    elif len(means_t10) == 2:
        mono = means_t10[0] >= means_t10[1]
        mono_status = "PARTIAL_TRUE" if mono else "PARTIAL_FALSE"
        # Not enough high-score buckets for full claim

    # Score IC
    ic: dict[str, Any] = {}
    for h in (5, 10, 20):
        xs, ys = [], []
        for p in pairs:
            if p.get(f"r{h}") is not None:
                xs.append(p["exit_score"])
                ys.append(p[f"r{h}"])
        if len(xs) < min_n:
            ic[str(h)] = {"status": "INSUFFICIENT_SAMPLE", "sample_count": len(xs), "spearman": None, "pearson": None}
        else:
            ic[str(h)] = {
                "status": "OK",
                "sample_count": len(xs),
                "spearman": _corr(xs, ys, "spearman"),
                "pearson": _corr(xs, ys, "pearson"),
            }

    # Scatter points for UI (capped)
    scatter = [
        {"exit_score": p["exit_score"], "t10": p.get("r10"), "t5": p.get("r5")}
        for p in pairs[:500]
        if p.get("r10") is not None
    ]

    return {
        "buckets": buckets_out,
        "monotonic_t10": mono,
        "monotonicity": mono_status,
        "ic": ic,
        "scatter_t10": scatter if n_total >= min_n else [],
        "sample_count": n_total,
        "minimum_sample": min_n,
        "bucket_minimum_sample": bucket_min,
        "status": "OK" if n_total >= min_n else "INSUFFICIENT_SAMPLE",
        "available": n_total >= min_n,
        "note": "Higher exit_score should map to weaker forward returns if predictive.",
        "versions": {"exit_version": exit_cfg.get("version")},
    }


def feature_ic_table(
    rows: list[dict[str, Any]],
    bars_by_symbol: dict,
    *,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    exit_cfg = load_exit_config(cfg)
    vcfg = dict(exit_cfg.get("validation") or {})
    min_n = int(vcfg.get("minimum_sample") or 30)
    horizons = list(vcfg.get("ic_horizons") or [5, 10, 20])

    # gather feature values + labels
    feat_names: set[str] = set()
    samples: list[dict[str, Any]] = []
    for r in rows:
        feats = r.get("features") or {}
        if isinstance(feats, dict) and feats and "trend_decay" not in feats:
            # maybe nested {name: {value, available}}
            pass
        bars = bars_by_symbol.get(str(r.get("symbol")))
        if bars is None:
            continue
        fr = forward_returns(
            bars,
            signal_date=r.get("signal_date"),
            horizons=horizons,
            base_mode="signal_close",
            price_field="close",
            adj_type="qfq",
        )
        flat: dict[str, float] = {}
        raw = r.get("features") or {}
        for name, meta in raw.items():
            if isinstance(meta, dict):
                if meta.get("available") and meta.get("value") is not None:
                    flat[name] = float(meta["value"])
                    feat_names.add(name)
            elif meta is not None:
                flat[name] = float(meta)
                feat_names.add(name)
        if not flat:
            continue
        lab = {}
        for h in horizons:
            cell = fr.get(str(h)) or {}
            if cell.get("available"):
                lab[h] = float(cell["return"])
        if lab:
            samples.append({"features": flat, "labels": lab})

    table = []
    for name in sorted(feat_names):
        row_out: dict[str, Any] = {"feature": name}
        for h in horizons:
            xs, ys = [], []
            for s in samples:
                if name in s["features"] and h in s["labels"]:
                    xs.append(s["features"][name])
                    ys.append(s["labels"][h])
            row_out[f"sample_{h}d"] = len(xs)
            if len(xs) < min_n:
                row_out[f"IC_{h}d"] = None
                row_out[f"status_{h}d"] = "INSUFFICIENT_SAMPLE"
            else:
                # exit features: higher → expect lower future return → IC should be negative if useful
                row_out[f"IC_{h}d"] = _corr(xs, ys, "spearman")
                row_out[f"status_{h}d"] = "OK"
        table.append(row_out)

    return {
        "features": table,
        "minimum_sample": min_n,
        "sample_rows": len(samples),
        "status": "OK" if len(samples) >= min_n else "INSUFFICIENT_SAMPLE",
        "available": len(samples) >= min_n,
    }


def feature_redundancy(
    rows: list[dict[str, Any]],
    *,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    exit_cfg = load_exit_config(cfg)
    thr = float((exit_cfg.get("validation") or {}).get("redundancy_threshold") or 0.8)
    mid = float((exit_cfg.get("validation") or {}).get("redundancy_medium_threshold") or 0.6)
    min_n = int((exit_cfg.get("validation") or {}).get("minimum_sample") or exit_cfg.get("minimum_sample") or 30)
    groups = dict(exit_cfg.get("feature_groups") or {})

    # matrix of feature values
    data: dict[str, list[float]] = {}
    for r in rows:
        raw = r.get("features") or {}
        vals = {}
        for name, meta in raw.items():
            if isinstance(meta, dict):
                if meta.get("available") and meta.get("value") is not None:
                    vals[name] = float(meta["value"])
            elif meta is not None:
                vals[name] = float(meta)
        if not vals:
            continue
        for k, v in vals.items():
            data.setdefault(k, []).append(v)
        # align lengths — pad missing with nan per row approach: rebuild
    # Better: list of dicts → DataFrame
    records = []
    for r in rows:
        raw = r.get("features") or {}
        rec = {}
        for name, meta in raw.items():
            if isinstance(meta, dict) and meta.get("available") and meta.get("value") is not None:
                rec[name] = float(meta["value"])
        if rec:
            records.append(rec)
    if len(records) < min_n:
        return {
            "available": False,
            "status": "INSUFFICIENT_SAMPLE",
            "sample_count": len(records),
            "minimum_sample": min_n,
            "pairs": [],
            "feature_groups": groups,
        }

    df = pd.DataFrame(records)
    # keep columns with enough non-null
    cols = [c for c in df.columns if df[c].notna().sum() >= min_n]
    pairs = []
    for i, a in enumerate(cols):
        for b in cols[i + 1 :]:
            sub = df[[a, b]].dropna()
            if len(sub) < min_n:
                continue
            pear = float(sub[a].corr(sub[b], method="pearson"))
            spear = float(sub[a].corr(sub[b], method="spearman"))
            pairs.append(
                {
                    "a": a,
                    "b": b,
                    "pearson": pear,
                    "spearman": spear,
                    "sample_count": len(sub),
                    "high_redundancy": abs(pear) > thr or abs(spear) > thr,
                    "redundancy": (
                        "HIGH_REDUNDANCY"
                        if abs(pear) >= thr or abs(spear) >= thr
                        else (
                            "MEDIUM_REDUNDANCY"
                            if abs(pear) >= mid or abs(spear) >= mid
                            else "LOW"
                        )
                    ),
                }
            )
    pairs.sort(key=lambda x: abs(x.get("spearman") or 0), reverse=True)
    return {
        "available": True,
        "status": "OK",
        "sample_count": len(records),
        "threshold": thr,
        "medium_threshold": mid,
        "pairs": pairs[:40],
        "high_redundancy_count": sum(1 for p in pairs if p["high_redundancy"]),
        "feature_groups": groups,
        "note": "Do not auto-drop features; review TREND/MOMENTUM groups for double-counting.",
    }


def summarize_giveback(values: list[float], *, minimum_sample: int = 30) -> dict[str, Any]:
    if len(values) < minimum_sample:
        return {
            "available": False,
            "status": "INSUFFICIENT_SAMPLE",
            "sample_count": len(values),
            "mean": None,
            "median": None,
            "p90": None,
        }
    s = pd.Series(values)
    return {
        "available": True,
        "status": "OK",
        "sample_count": len(values),
        "mean": float(s.mean()),
        "median": float(s.median()),
        "p90": float(s.quantile(0.9)),
    }
