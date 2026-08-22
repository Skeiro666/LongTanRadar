"""V5.4 Prediction Calibration — EER and confidence vs realized alpha."""

from __future__ import annotations

from typing import Any

import pandas as pd

from ashare.config_loaders import load_yaml_config
from ashare.research.signal_attribution import horizon_metrics


def _eer_from_report(report: dict[str, Any]) -> dict[str, Any]:
    hyps = list(report.get("research_hypotheses") or [])
    for h in hyps:
        if not isinstance(h, dict):
            continue
        inv = dict(h.get("investment_hypothesis") or {})
        eer = dict(inv.get("expected_excess_return") or {})
        if eer.get("available") and eer.get("value") is not None:
            return eer
    snap_meta = dict((report.get("snapshot") or {}).get("candidate_score_meta") or {})
    eer = dict(snap_meta.get("expected_excess_return") or {})
    return eer


def _confidence_from_report(report: dict[str, Any]) -> float | None:
    c = (report.get("chairman") or {}).get("confidence")
    if c is None:
        c = (report.get("decision") or {}).get("confidence")
    if c is None:
        return None
    try:
        v = float(c)
        return v / 100.0 if v > 1.0 else v
    except (TypeError, ValueError):
        return None


def _eer_bucket(val: float) -> str:
    if val < 0.02:
        return "0_2pct"
    if val < 0.05:
        return "2_5pct"
    if val < 0.10:
        return "5_10pct"
    return "10pct_plus"


def _conf_bucket(val: float) -> str:
    edges = [(0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 1.01)]
    for lo, hi in edges:
        if lo <= val < hi:
            return f"{int(lo*100)}_{int(hi*100)}"
    return "unknown"


def build_calibration(
    reports: list[dict[str, Any]],
    outcomes: list[dict[str, Any]],
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    acfg = dict(load_yaml_config(cfg, "research").get("attribution") or {})
    horizons = list(acfg.get("horizons_days") or [1, 5, 10, 20])
    minimum_sample = int(acfg.get("minimum_sample") or 5)

    outcome_by_sym = {str(o.get("symbol")): o for o in outcomes}
    report_by_sym = {str(r.get("symbol")): r for r in reports}

    eer_rows: list[dict[str, Any]] = []
    conf_rows: list[dict[str, Any]] = []

    for sym, rep in report_by_sym.items():
        o = outcome_by_sym.get(sym)
        if not o:
            continue
        eer = _eer_from_report(rep)
        conf = _confidence_from_report(rep)
        if eer.get("available") and eer.get("value") is not None:
            eer_rows.append({"predicted": float(eer["value"]), "outcome": o, "symbol": sym})
        if conf is not None:
            conf_rows.append({"confidence": conf, "outcome": o, "symbol": sym})

    eer_buckets: dict[str, dict[str, Any]] = {}
    for row in eer_rows:
        b = _eer_bucket(row["predicted"])
        eer_buckets.setdefault(b, {"predicted": [], "realized": {str(h): [] for h in horizons}})
        eer_buckets[b]["predicted"].append(row["predicted"])
        for h in horizons:
            m = horizon_metrics(row["outcome"], h)
            if m and m.get("selection_alpha") is not None:
                eer_buckets[b]["realized"][str(h)].append(float(m["selection_alpha"]))
            elif m:
                eer_buckets[b]["realized"][str(h)].append(float(m["realized_return"]))

    eer_calibration: dict[str, Any] = {}
    for b, data in eer_buckets.items():
        pred_mean = float(pd.Series(data["predicted"]).mean()) if data["predicted"] else None
        realized_by_h: dict[str, Any] = {}
        for h in horizons:
            h_key = str(h)
            vals = data["realized"][h_key]
            if len(vals) < minimum_sample:
                realized_by_h[h_key] = {"insufficient_sample": True, "sample_count": len(vals)}
            else:
                rm = float(pd.Series(vals).mean())
                realized_by_h[h_key] = {
                    "insufficient_sample": False,
                    "sample_count": len(vals),
                    "mean_realized": rm,
                    "mean_predicted": pred_mean,
                    "bias": (pred_mean - rm) if pred_mean is not None else None,
                }
        eer_calibration[b] = {"mean_predicted": pred_mean, "horizons": realized_by_h}

    conf_buckets: dict[str, dict[str, Any]] = {}
    for row in conf_rows:
        b = _conf_bucket(row["confidence"])
        conf_buckets.setdefault(b, {"confidence": [], "hits_5": [], "hits_10": []})
        conf_buckets[b]["confidence"].append(row["confidence"])
        for h, key in [(5, "hits_5"), (10, "hits_10")]:
            m = horizon_metrics(row["outcome"], h)
            if m:
                hit = float(m.get("selection_alpha") or m.get("realized_return") or 0) > 0
                conf_buckets[b][key].append(hit)

    conf_calibration: dict[str, Any] = {}
    for b, data in conf_buckets.items():
        n = len(data["confidence"])
        if n < minimum_sample:
            conf_calibration[b] = {"insufficient_sample": True, "sample_count": n}
        else:
            conf_calibration[b] = {
                "insufficient_sample": False,
                "sample_count": n,
                "mean_confidence": float(pd.Series(data["confidence"]).mean()),
                "t5_hit_rate": float(pd.Series(data["hits_5"]).mean()) if data["hits_5"] else None,
                "t10_hit_rate": float(pd.Series(data["hits_10"]).mean()) if data["hits_10"] else None,
            }

    overall_bias = None
    all_pred, all_real = [], []
    for b, cal in eer_calibration.items():
        for h_data in (cal.get("horizons") or {}).values():
            if not h_data.get("insufficient_sample") and h_data.get("bias") is not None:
                all_pred.append(h_data.get("mean_predicted") or 0)
                all_real.append(h_data.get("mean_realized") or 0)
    if all_pred and all_real:
        overall_bias = float(pd.Series(all_pred).mean()) - float(pd.Series(all_real).mean())

    return {
        "available": bool(eer_rows or conf_rows),
        "minimum_sample": minimum_sample,
        "eer_calibration": eer_calibration,
        "confidence_calibration": conf_calibration,
        "overall_eer_bias": overall_bias,
        "eer_sample_count": len(eer_rows),
        "confidence_sample_count": len(conf_rows),
        "note": "Only records with available expected_excess_return enter EER buckets",
    }
