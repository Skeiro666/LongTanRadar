from __future__ import annotations

"""Honest Exit Validation final answers — never fabricates alpha."""

from typing import Any


def build_exit_validation_report(pack: dict[str, Any]) -> dict[str, Any]:
    """
    Answer the 13 mandatory questions from research metrics.
    If sample insufficient → say so explicitly.
    """
    cal = pack.get("calibration") or {}
    ic = (cal.get("ic") or {})
    feat_ic = pack.get("feature_ic") or {}
    red = pack.get("redundancy") or {}
    alpha = pack.get("exit_alpha") or {}
    bt = (alpha.get("backtest") or pack.get("backtest") or {})
    strats = bt.get("strategies") or alpha.get("strategies") or {}
    # strategies may be list (alpha) or dict (backtest)
    strat_map: dict[str, Any] = {}
    if isinstance(strats, list):
        for s in strats:
            strat_map[str(s.get("id"))] = s
    else:
        strat_map = dict(strats)

    ml = pack.get("ml") or {}
    ml_cmp = pack.get("ml_vs_heuristic") or ml.get("vs_heuristic") or {}
    leakage = pack.get("leakage_tests") or {}

    min_n = int(pack.get("minimum_sample") or cal.get("minimum_sample") or 30)
    n = int(pack.get("n_entries") or cal.get("sample_count") or 0)
    sample_ok = n >= min_n and cal.get("status") != "INSUFFICIENT_SAMPLE"

    def _ic_cell(h: str) -> Any:
        cell = ic.get(h) or ic.get(str(h)) or {}
        if cell.get("status") == "INSUFFICIENT_SAMPLE" or cell.get("spearman") is None:
            return "INSUFFICIENT_SAMPLE"
        return {
            "spearman": cell.get("spearman"),
            "pearson": cell.get("pearson"),
            "sample_count": cell.get("sample_count"),
        }

    # Effective features: IC_10d most negative (exit features predict lower fwd return)
    effective = []
    weak = []
    for row in feat_ic.get("features") or []:
        ic10 = row.get("IC_10d")
        if ic10 is None:
            continue
        if ic10 < -0.05:
            effective.append({"feature": row["feature"], "IC_10d": ic10})
        elif abs(ic10) < 0.02:
            weak.append(row["feature"])
    effective.sort(key=lambda x: x["IC_10d"])

    high_red = [p for p in (red.get("pairs") or []) if p.get("high_redundancy")]

    no_exit = strat_map.get("no_exit") or {}
    fixed = strat_map.get("fixed_stop") or {}
    engine = strat_map.get("exit_engine") or {}

    def _better(a: dict, b: dict, key: str, higher_better: bool = True) -> str:
        if a.get("status") == "INSUFFICIENT_SAMPLE" or b.get("status") == "INSUFFICIENT_SAMPLE":
            return "INSUFFICIENT_SAMPLE"
        va, vb = a.get(key), b.get(key)
        if va is None or vb is None:
            # try nested net
            va = va if va is not None else (a.get("net") or {}).get(key.replace("total_return", "total_return"))
            vb = vb if vb is not None else (b.get("net") or {}).get("total_return" if key == "total_return" else key)
        if va is None or vb is None:
            return "INSUFFICIENT_SAMPLE"
        if higher_better:
            return "YES" if float(va) > float(vb) else "NO"
        return "YES" if float(va) < float(vb) else "NO"

    eq = engine.get("exit_quality") or {}
    gb_engine = engine.get("mean_giveback")
    gb_no = no_exit.get("mean_giveback")
    gb_fixed = fixed.get("mean_giveback")
    giveback_delta = None
    if gb_engine is not None and gb_no is not None:
        giveback_delta = float(gb_no) - float(gb_engine)

    ml_better = "INSUFFICIENT_SAMPLE"
    if ml_cmp.get("available") and ml_cmp.get("ml_improves") is not None:
        ml_better = "YES" if ml_cmp.get("ml_improves") else "NO"
    elif ml.get("status") == "INSUFFICIENT_SAMPLE" or not ml.get("trained"):
        ml_better = "INSUFFICIENT_SAMPLE — kept HEURISTIC"

    mono = cal.get("monotonicity")
    if mono is None:
        mono = "TRUE" if cal.get("monotonic_t10") else ("FALSE" if sample_ok else "INSUFFICIENT_SAMPLE")

    answers = {
        "1_monotonicity": mono if sample_ok or mono in {"TRUE", "FALSE"} else "INSUFFICIENT_SAMPLE",
        "2_exit_score_ic": {
            "T+5": _ic_cell("5"),
            "T+10": _ic_cell("10"),
            "T+20": _ic_cell("20"),
        },
        "3_effective_features": effective[:8] if feat_ic.get("available") else "INSUFFICIENT_SAMPLE",
        "4_redundant_features": high_red[:15] if red.get("available") else "INSUFFICIENT_SAMPLE",
        "5_exit_vs_no_exit": _better(engine, no_exit, "total_return", higher_better=True),
        "6_exit_vs_fixed_stop": _better(engine, fixed, "total_return", higher_better=True),
        "7_giveback_reduction_vs_no_exit": giveback_delta if giveback_delta is not None else "INSUFFICIENT_SAMPLE",
        "7b_giveback_vs_fixed_stop": (
            (float(gb_fixed) - float(gb_engine)) if gb_fixed is not None and gb_engine is not None else "INSUFFICIENT_SAMPLE"
        ),
        "8_early_exit_pct": eq.get("early_pct") if eq.get("available") else "INSUFFICIENT_SAMPLE",
        "9_good_exit_pct": eq.get("good_pct") if eq.get("available") else "INSUFFICIENT_SAMPLE",
        "10_late_exit_pct": eq.get("late_pct") if eq.get("available") else "INSUFFICIENT_SAMPLE",
        "11_ml_vs_heuristic": ml_better,
        "12_sample_sufficient": sample_ok,
        "12b_n_entries": n,
        "12c_minimum_sample": min_n,
        "13_future_leakage": (
            "PASS — no leakage detected"
            if leakage.get("passed")
            else ("FAIL" if leakage.get("passed") is False else "NOT_RUN")
        ),
    }

    # Honest verdict
    has_alpha = False
    if sample_ok and mono == "TRUE":
        ic10 = _ic_cell("10")
        if isinstance(ic10, dict) and ic10.get("spearman") is not None and float(ic10["spearman"]) < -0.02:
            has_alpha = True
    if answers["5_exit_vs_no_exit"] == "YES" and sample_ok:
        has_alpha = True

    verdict = (
        "Exit Engine shows preliminary predictive structure on research bootstrap — still research-only."
        if has_alpha
        else (
            "INSUFFICIENT_SAMPLE to claim Exit Alpha."
            if not sample_ok
            else "Exit Engine does NOT show clear Alpha vs baselines on available data. Do not complicate further — revisit features/labels/backtest."
        )
    )

    return {
        "answers": answers,
        "verdict": verdict,
        "has_exit_alpha_claim": has_alpha,
        "feature_groups": red.get("feature_groups") or {},
        "hold_score_formula": "1 - exit_score",
        "production_logic_changed": False,
        "note": "Research only. BUY / live broker untouched.",
    }
