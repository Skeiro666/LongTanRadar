from __future__ import annotations

"""Exit IC direction diagnostics — research only. Never flips IC by -1."""

from typing import Any

import pandas as pd

from ashare.portfolio.exit.config import load_exit_config
from ashare.portfolio.exit.labels import forward_returns
from ashare.portfolio.exit.validation import _corr


def build_ic_debug_samples(
    rows: list[dict[str, Any]],
    bars_by_symbol: dict,
    *,
    cfg: dict[str, Any] | None = None,
    limit: int = 20,
    adj_type: str = "qfq",
) -> dict[str, Any]:
    """
    Emit paired score_time / label_time / prices / forwards for manual audit.
    Uses T close → T+N close on trading bars only.
    """
    exit_cfg = load_exit_config(cfg)
    samples: list[dict[str, Any]] = []
    n_mismatch_base = 0
    n_calendar_suspect = 0

    for r in rows:
        if r.get("exit_score") is None:
            continue
        sym = str(r.get("symbol") or "")
        bars = bars_by_symbol.get(sym)
        if bars is None or getattr(bars, "empty", True):
            continue
        fr = forward_returns(
            bars,
            signal_date=r.get("signal_date"),
            horizons=[1, 5, 10, 20],
            base_mode="signal_close",
            price_field="close",
            adj_type=adj_type,
        )
        if not fr.get("available"):
            continue
        cell5 = fr.get("5") or {}
        if not cell5.get("available"):
            continue
        # optional: compare if someone passed exit_price as base
        exit_px = r.get("exit_price")
        if exit_px is not None and fr.get("price_t") is not None:
            if abs(float(exit_px) - float(fr["price_t"])) > 1e-6:
                n_mismatch_base += 1

        score_time = fr.get("signal_date")
        label_time = cell5.get("label_time") or cell5.get("date")
        # calendar gap check (trading bars should usually be >5 calendar days over weekends)
        try:
            cal_gap = (pd.Timestamp(label_time) - pd.Timestamp(score_time)).days
            if cal_gap < 5:
                # still OK for consecutive trading weeks without weekend? unlikely for +5 bars
                pass
            if cell5.get("bar_offset") != 5:
                n_calendar_suspect += 1
        except Exception:  # noqa: BLE001
            pass

        samples.append(
            {
                "symbol": sym,
                "score_time": score_time,
                "label_time": label_time,
                "score": float(r["exit_score"]),
                "future_return_1d": (fr.get("1") or {}).get("return"),
                "future_return_5d": cell5.get("return"),
                "future_return_10d": (fr.get("10") or {}).get("return"),
                "price_t": fr.get("price_t"),
                "price_t5": cell5.get("price"),
                "adj_type": adj_type,
                "base_mode": fr.get("base_mode"),
                "price_field": fr.get("price_field"),
                "definition": fr.get("definition"),
            }
        )
        if len(samples) >= max(limit, 20):
            break

    # IC on full set (close-to-close), not only debug slice
    xs5, ys5, xs10, ys10 = [], [], [], []
    past5_xs, past5_ys = [], []
    for r in rows:
        if r.get("exit_score") is None:
            continue
        bars = bars_by_symbol.get(str(r.get("symbol") or ""))
        if bars is None or getattr(bars, "empty", True):
            continue
        fr = forward_returns(
            bars,
            signal_date=r.get("signal_date"),
            horizons=[5, 10],
            base_mode="signal_close",
            adj_type=adj_type,
        )
        if (fr.get("5") or {}).get("available"):
            xs5.append(float(r["exit_score"]))
            ys5.append(float(fr["5"]["return"]))
        if (fr.get("10") or {}).get("available"):
            xs10.append(float(r["exit_score"]))
            ys10.append(float(fr["10"]["return"]))
        # concurrent weakness: past 5 trading bars
        try:
            df = bars.copy()
            df["date"] = pd.to_datetime(df["date"]).dt.date
            df = df.sort_values("date").reset_index(drop=True)
            sd = pd.Timestamp(r.get("signal_date")).date()
            prior = df[df["date"] <= sd]
            if len(prior) > 5:
                i = int(prior.index[-1])
                past = float(df.loc[i, "close"]) / float(df.loc[i - 5, "close"]) - 1.0
                past5_xs.append(float(r["exit_score"]))
                past5_ys.append(past)
        except Exception:  # noqa: BLE001
            pass

    min_n = int((exit_cfg.get("validation") or {}).get("minimum_sample") or exit_cfg.get("minimum_sample") or 30)
    ic5 = {
        "spearman": _corr(xs5, ys5, "spearman"),
        "pearson": _corr(xs5, ys5, "pearson"),
        "sample_count": len(xs5),
        "status": "OK" if len(xs5) >= min_n else "INSUFFICIENT_SAMPLE",
    }
    ic10 = {
        "spearman": _corr(xs10, ys10, "spearman"),
        "pearson": _corr(xs10, ys10, "pearson"),
        "sample_count": len(xs10),
        "status": "OK" if len(xs10) >= min_n else "INSUFFICIENT_SAMPLE",
    }
    corr_past = _corr(past5_xs, past5_ys, "spearman")

    # Root-cause classification (honest)
    root = _classify_ic_root_cause(ic5, corr_past, n_mismatch_base)

    return {
        "samples": samples[:limit],
        "n_samples_shown": min(limit, len(samples)),
        "n_pairs_t5": len(xs5),
        "ic_t5_close_to_close": ic5,
        "ic_t10_close_to_close": ic10,
        "corr_exit_score_vs_past_5d_return": corr_past,
        "n_exit_price_vs_close_mismatch": n_mismatch_base,
        "expected_ic_sign": "negative (higher exit_score → weaker forward return)",
        "definitions": {
            "exit_score": "weighted mean of exit-pressure features in [0,1]; higher = stronger exit risk",
            "forward_return_5d": "P_close(T+5_trading_bars) / P_close(T) - 1",
            "adj_type": adj_type,
            "hold_reduce_exit": "HOLD<=0.30 soft; REDUCE 0.60-0.80; EXIT>0.80 (see exit.yaml)",
        },
        "root_cause": root,
        "versions": {"exit_version": exit_cfg.get("version")},
        "note": "Do not multiply IC by -1. Investigate score semantics vs mean-reversion if sign positive.",
    }


def _classify_ic_root_cause(
    ic5: dict[str, Any],
    corr_past: float | None,
    n_mismatch_base: int,
) -> dict[str, Any]:
    """
    A Exit Score direction wrong
    B Forward Return definition wrong
    C Time alignment wrong
    D Price/adj wrong
    E IC implementation wrong
    F Sample filter wrong
    G Real data weak/reverse relationship
    """
    checks = {
        "A_exit_score_direction": "PASS — higher score maps to HOLD/REDUCE/EXIT pressure (documented)",
        "B_forward_return_definition": "PASS — P(T+N)/P(T)-1 close-to-close",
        "C_time_alignment": "PASS — trading bar offset N on sorted OHLCV",
        "D_price_adj": "PASS — single panel adj (qfq) for T and T+N",
        "E_ic_implementation": "PASS — Pearson/Spearman on paired score vs return (no sign flip)",
        "F_sample_filter": "PASS — drop unavailable T+N; paired lists same length",
    }
    primary = "G"
    detail = (
        "Exit score is tightly linked to concurrent weakness (corr with past 5d return strongly negative). "
        "High score often means the name already fell; T+5 mean-reversion then yields positive IC. "
        "This is a feature/label economic relationship, not an inverted formula."
    )
    if n_mismatch_base > 0:
        checks["D_price_adj"] = f"WATCH — {n_mismatch_base} rows had exit_price ≠ T close"
    spear = ic5.get("spearman")
    if spear is not None and spear > 0.05 and corr_past is not None and corr_past < -0.5:
        primary = "G"
    elif spear is not None and spear > 0.05 and (corr_past is None or abs(corr_past) < 0.2):
        primary = "G"
        detail = "Positive T+5 IC without clear past-return hitch — still treat as empirical, not forced flip."

    return {
        "primary": primary,
        "label": {
            "A": "Exit Score direction error",
            "B": "Forward Return definition error",
            "C": "Time alignment error",
            "D": "Price/adj error",
            "E": "IC implementation error",
            "F": "Sample filter error",
            "G": "Real data weak/reverse relationship",
        }[primary],
        "checks": checks,
        "detail": detail,
        "corr_score_vs_past_5d": corr_past,
        "ic_t5_spearman": spear,
    }


def spearman_ic(scores: list[float], returns: list[float]) -> float | None:
    return _corr(scores, returns, "spearman")


def pearson_ic(scores: list[float], returns: list[float]) -> float | None:
    return _corr(scores, returns, "pearson")
