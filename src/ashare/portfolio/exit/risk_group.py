from __future__ import annotations

"""RISK GROUP redundancy / LOO / group IC — research only. Never writes production weights."""

from typing import Any

import numpy as np
import pandas as pd

from ashare.portfolio.exit.config import load_exit_config
from ashare.portfolio.exit.heuristic import compute_exit_score
from ashare.portfolio.exit.labels import forward_returns
from ashare.portfolio.exit.validation import _corr, _pair_corr


def _flat_features(raw: dict[str, Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    for name, meta in (raw or {}).items():
        if isinstance(meta, dict):
            if meta.get("available") and meta.get("value") is not None:
                out[name] = float(meta["value"])
        elif meta is not None:
            out[name] = float(meta)
    return out


def _feature_registry(exit_cfg: dict[str, Any]) -> list[dict[str, Any]]:
    weights = dict(exit_cfg.get("weights") or {})
    groups = dict(exit_cfg.get("feature_groups") or {})
    name_to_group: dict[str, str] = {}
    for g, names in groups.items():
        for n in names or []:
            name_to_group[str(n)] = str(g)
    rows = []
    for name, w in weights.items():
        rows.append(
            {
                "feature": name,
                "group": name_to_group.get(name, "UNGROUPED"),
                "weight": float(w),
                "source": "config/exit.yaml",
            }
        )
    return rows


def _redundancy_level(abs_corr: float, high: float, mid: float) -> str:
    if abs_corr >= high:
        return "HIGH_REDUNDANCY"
    if abs_corr >= mid:
        return "MEDIUM_REDUNDANCY"
    return "LOW"


def analyze_risk_group(
    rows: list[dict[str, Any]],
    bars_by_symbol: dict,
    *,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Full RISK group research pack. Does not mutate exit.yaml production weights."""
    exit_cfg = load_exit_config(cfg)
    vcfg = dict(exit_cfg.get("validation") or {})
    min_n = int(vcfg.get("minimum_sample") or exit_cfg.get("minimum_sample") or 30)
    high_thr = float(vcfg.get("redundancy_threshold") or 0.8)
    mid_thr = float(vcfg.get("redundancy_medium_threshold") or 0.6)
    groups = dict(exit_cfg.get("feature_groups") or {})
    risk_feats = list(groups.get("RISK") or ["drawdown", "volatility", "price_extension", "breakout_failure", "profit_loss"])
    weights = dict(exit_cfg.get("weights") or {})
    horizons = [1, 5, 10, 20]

    registry = _feature_registry(exit_cfg)

    # Build aligned sample matrix + labels + scores
    records: list[dict[str, Any]] = []
    for r in rows:
        flat = _flat_features(r.get("features") or {})
        if not flat:
            continue
        bars = bars_by_symbol.get(str(r.get("symbol") or ""))
        if bars is None or getattr(bars, "empty", True):
            continue
        fr = forward_returns(
            bars,
            signal_date=r.get("signal_date"),
            horizons=horizons,
            base_mode="signal_close",
        )
        labs = {}
        for h in horizons:
            cell = fr.get(str(h)) or {}
            if cell.get("available") and cell.get("return") is not None:
                labs[h] = float(cell["return"])
        if not labs:
            continue
        pack = {"features": {k: {"value": v, "available": True} for k, v in flat.items()}}
        score_pack = compute_exit_score(pack, cfg)
        rec = {
            **flat,
            "exit_score": float(score_pack.get("exit_score") or 0),
            "symbol": r.get("symbol"),
            "signal_date": r.get("signal_date"),
        }
        for h, v in labs.items():
            rec[f"r{h}"] = v
        records.append(rec)

    if len(records) < min_n:
        return {
            "available": False,
            "status": "INSUFFICIENT_SAMPLE",
            "sample_count": len(records),
            "minimum_sample": min_n,
            "registry": registry,
            "risk_features": risk_feats,
        }

    df = pd.DataFrame(records)

    # --- Feature IC ---
    feature_ic = []
    for name in sorted(set(list(weights.keys()) + risk_feats)):
        if name not in df.columns:
            continue
        row: dict[str, Any] = {
            "feature": name,
            "group": next((x["group"] for x in registry if x["feature"] == name), "UNGROUPED"),
            "weight": float(weights.get(name, 0.0)),
        }
        for h in horizons:
            col = f"r{h}"
            sub = df[[name, col]].dropna()
            row[f"sample_{h}d"] = len(sub)
            if len(sub) < min_n:
                row[f"IC_{h}d"] = None
                row[f"status_{h}d"] = "INSUFFICIENT_SAMPLE"
            else:
                row[f"IC_{h}d"] = _corr(sub[name].tolist(), sub[col].tolist(), "spearman")
                row[f"status_{h}d"] = "OK"
        feature_ic.append(row)

    # --- RISK correlation matrix ---
    risk_present = [f for f in risk_feats if f in df.columns and df[f].notna().sum() >= min_n]
    corr_pearson: dict[str, dict[str, float | None]] = {}
    corr_spearman: dict[str, dict[str, float | None]] = {}
    pairs = []
    for a in risk_present:
        corr_pearson[a] = {}
        corr_spearman[a] = {}
        for b in risk_present:
            if a == b:
                corr_pearson[a][b] = 1.0
                corr_spearman[a][b] = 1.0
                continue
            sub = df[[a, b]].dropna()
            if len(sub) < min_n:
                corr_pearson[a][b] = None
                corr_spearman[a][b] = None
                continue
            p = _pair_corr(sub[a], sub[b], "pearson")
            s = _pair_corr(sub[a], sub[b], "spearman")
            corr_pearson[a][b] = p
            corr_spearman[a][b] = s
            if a < b and (p is not None or s is not None):
                abs_s = abs(s or 0)
                pairs.append(
                    {
                        "a": a,
                        "b": b,
                        "pearson": p,
                        "spearman": s,
                        "sample_count": len(sub),
                        "redundancy": _redundancy_level(abs_s, high_thr, mid_thr),
                        "high_redundancy": abs_s >= high_thr,
                    }
                )
    pairs.sort(key=lambda x: abs(x.get("spearman") or 0), reverse=True)

    # --- Mutual information (optional) ---
    mi_pairs = []
    try:
        from sklearn.feature_selection import mutual_info_regression

        for a in risk_present:
            for b in risk_present:
                if a >= b:
                    continue
                sub = df[[a, b]].dropna()
                if len(sub) < min_n:
                    continue
                mi = float(
                    mutual_info_regression(
                        sub[[a]].values, sub[b].values, random_state=0, n_neighbors=3
                    )[0]
                )
                mi_pairs.append({"a": a, "b": b, "mutual_info": mi, "sample_count": len(sub)})
        mi_status = "OK"
    except Exception as exc:  # noqa: BLE001
        mi_status = f"UNAVAILABLE ({exc})"

    # --- Group score IC ---
    def _group_score(row: pd.Series, feats: list[str]) -> float | None:
        num, den = 0.0, 0.0
        for f in feats:
            if f not in row or pd.isna(row[f]):
                continue
            w = float(weights.get(f, 0.0))
            if w <= 0:
                continue
            num += float(row[f]) * w
            den += w
        return (num / den) if den > 0 else None

    gscores = df.apply(lambda r: _group_score(r, risk_present), axis=1)
    group_ic = {}
    for h in horizons:
        col = f"r{h}"
        mask = gscores.notna() & df[col].notna()
        xs = gscores[mask].tolist()
        ys = df.loc[mask, col].tolist()
        if len(xs) < min_n:
            group_ic[str(h)] = {"status": "INSUFFICIENT_SAMPLE", "spearman": None, "sample_count": len(xs)}
        else:
            group_ic[str(h)] = {
                "status": "OK",
                "spearman": _corr(xs, ys, "spearman"),
                "pearson": _corr(xs, ys, "pearson"),
                "sample_count": len(xs),
            }

    # --- Leave-one-out ---
    loo = []
    base_scores = df["exit_score"].tolist()
    base_ic5 = _corr(base_scores, df["r5"].dropna().tolist()[: len(base_scores)], "spearman")
    # align properly
    base_sub = df[["exit_score", "r5", "r10"]].dropna()
    base_ic5 = _corr(base_sub["exit_score"].tolist(), base_sub["r5"].tolist(), "spearman")
    base_ic10 = _corr(base_sub["exit_score"].tolist(), base_sub["r10"].tolist(), "spearman")

    for drop in risk_present + ["__ALL_RISK__"]:
        xs5, ys5, xs10, ys10 = [], [], [], []
        override_w = dict(weights)
        if drop == "__ALL_RISK__":
            for f in risk_feats:
                override_w[f] = 0.0
        else:
            override_w[drop] = 0.0
        local_cfg = {**(cfg or {}), "exit": {"weights": override_w}}
        for _, row in df.iterrows():
            feat_map = {}
            for name in weights:
                if name in row and not pd.isna(row[name]):
                    feat_map[name] = {"value": float(row[name]), "available": True}
            sp = compute_exit_score({"features": feat_map}, local_cfg)
            if not sp.get("available"):
                continue
            sc = float(sp["exit_score"])
            if not pd.isna(row.get("r5")):
                xs5.append(sc)
                ys5.append(float(row["r5"]))
            if not pd.isna(row.get("r10")):
                xs10.append(sc)
                ys10.append(float(row["r10"]))
        label = f"RISK - {drop}" if drop != "__ALL_RISK__" else "Remove RISK GROUP"
        ic5 = _corr(xs5, ys5, "spearman") if len(xs5) >= min_n else None
        loo.append(
            {
                "ablation": label,
                "dropped": drop,
                "IC_5d": ic5,
                "IC_10d": _corr(xs10, ys10, "spearman") if len(xs10) >= min_n else None,
                "sample_5d": len(xs5),
                "sample_10d": len(xs10),
                "status": "OK" if len(xs5) >= min_n else "INSUFFICIENT_SAMPLE",
                "delta_IC_5d_vs_baseline": (
                    None if base_ic5 is None or ic5 is None else round(float(ic5) - float(base_ic5), 6)
                ),
            }
        )

    # --- Candidate weights (research suggestion only) ---
    candidate = _suggest_weights(weights, risk_feats, pairs, feature_ic, high_thr)

    # --- Answers ---
    high_pairs = [p for p in pairs if p["high_redundancy"]]
    best_ic = sorted(
        [f for f in feature_ic if f.get("group") == "RISK" and f.get("IC_10d") is not None],
        key=lambda x: (x["IC_10d"] if x["IC_10d"] is not None else 0),
    )
    worst_delta = sorted(
        [x for x in loo if x.get("delta_IC_5d_vs_baseline") is not None],
        key=lambda x: abs(x["delta_IC_5d_vs_baseline"]),
        reverse=True,
    )

    answers = {
        "1_risk_group_redundant": bool(high_pairs) or any(p["redundancy"] == "MEDIUM_REDUNDANCY" for p in pairs),
        "2_highest_corr_pair": high_pairs[0] if high_pairs else (pairs[0] if pairs else None),
        "3_best_feature_ic": best_ic[0] if best_ic else None,
        "4_low_incremental": _low_incremental(risk_present, pairs, feature_ic),
        "5_loo_largest_delta": worst_delta[0] if worst_delta else None,
        "6_risk_group_effective": _group_effective(group_ic),
        "7_suggest_reweight": bool(high_pairs),
        "8_candidate_weights": candidate,
        "9_suggest_delete": False,  # never auto-delete this stage
        "production_weights_changed": False,
    }

    # UI rows
    ui_rows = []
    for f in feature_ic:
        if f["feature"] not in risk_feats and f.get("group") != "RISK":
            continue
        max_red = "LOW"
        for p in pairs:
            if f["feature"] in (p["a"], p["b"]):
                if p["redundancy"] == "HIGH_REDUNDANCY":
                    max_red = "HIGH_REDUNDANCY"
                    break
                if p["redundancy"] == "MEDIUM_REDUNDANCY":
                    max_red = "MEDIUM_REDUNDANCY"
        ic10 = f.get("IC_10d")
        contrib = "LOW"
        if ic10 is not None:
            if ic10 < -0.1:
                contrib = "HIGH"
            elif ic10 < -0.05:
                contrib = "MEDIUM"
            elif ic10 > 0.05:
                contrib = "WRONG_SIGN"
        ui_rows.append(
            {
                "group": f.get("group"),
                "feature": f["feature"],
                "weight": f.get("weight"),
                "IC_5d": f.get("IC_5d"),
                "IC_10d": ic10,
                "IC_20d": f.get("IC_20d"),
                "redundancy": max_red,
                "contribution": contrib,
            }
        )

    return {
        "available": True,
        "status": "OK",
        "sample_count": len(records),
        "minimum_sample": min_n,
        "thresholds": {"high": high_thr, "medium": mid_thr},
        "registry": registry,
        "risk_features": risk_feats,
        "feature_ic": feature_ic,
        "correlation_matrix_pearson": corr_pearson,
        "correlation_matrix_spearman": corr_spearman,
        "pairs": pairs,
        "mutual_info": {"status": mi_status, "pairs": mi_pairs[:20]},
        "group_ic": group_ic,
        "baseline_ic": {"IC_5d": base_ic5, "IC_10d": base_ic10, "sample_count": len(base_sub)},
        "leave_one_out": loo,
        "candidate_weights": candidate,
        "answers": answers,
        "ui_rows": ui_rows,
        "note": "Research only — candidate weights NOT applied to production exit.yaml.",
    }


def _low_incremental(
    risk_feats: list[str],
    pairs: list[dict],
    feature_ic: list[dict],
) -> list[str]:
    """Features that are highly redundant and weak IC."""
    ic_map = {f["feature"]: f.get("IC_10d") for f in feature_ic}
    out = []
    for p in pairs:
        if not p.get("high_redundancy"):
            continue
        for name in (p["a"], p["b"]):
            ic = ic_map.get(name)
            if ic is None or abs(ic) < 0.05:
                if name not in out:
                    out.append(name)
    return out


def _group_effective(group_ic: dict[str, Any]) -> str:
    cell = group_ic.get("10") or {}
    if cell.get("status") != "OK" or cell.get("spearman") is None:
        return "INSUFFICIENT_SAMPLE"
    s = float(cell["spearman"])
    if s < -0.05:
        return "YES_WEAK"
    if s > 0.05:
        return "REVERSE_SIGN"
    return "NEAR_ZERO"


def _suggest_weights(
    weights: dict[str, float],
    risk_feats: list[str],
    pairs: list[dict],
    feature_ic: list[dict],
    high_thr: float,
) -> dict[str, Any]:
    """Down-weight one side of HIGH_REDUNDANCY pairs; boost better IC. Suggestion only."""
    suggested = {k: float(v) for k, v in weights.items()}
    ic_map = {f["feature"]: f.get("IC_10d") for f in feature_ic}
    notes = []
    for p in pairs:
        if abs(p.get("spearman") or 0) < high_thr:
            continue
        a, b = p["a"], p["b"]
        ica, icb = ic_map.get(a), ic_map.get(b)
        # keep the more negative IC (better for exit); shrink the other
        if ica is None or icb is None:
            continue
        if ica <= icb:
            keep, shrink = a, b
        else:
            keep, shrink = b, a
        old = suggested.get(shrink, 0.0)
        new = round(old * 0.6, 4)
        if new != old:
            suggested[shrink] = new
            notes.append(f"{shrink}: {old} → {new} (redundant with {keep}, weaker IC)")
    # slight boost volatility if strongest negative IC in RISK
    if "volatility" in suggested and (ic_map.get("volatility") or 0) < -0.2:
        old = suggested["volatility"]
        suggested["volatility"] = round(min(0.12, old * 1.15), 4)
        if suggested["volatility"] != old:
            notes.append(f"volatility: {old} → {suggested['volatility']} (strongest RISK IC)")

    return {
        "current": {k: float(weights.get(k, 0)) for k in risk_feats},
        "suggested_risk": {k: suggested.get(k, 0.0) for k in risk_feats},
        "suggested_full": suggested,
        "notes": notes,
        "applied_to_production": False,
    }
