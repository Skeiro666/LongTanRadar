"""V5.4 Alpha Lab — aggregate validation metrics for dashboard."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _status_from_ablation(ab: dict[str, Any] | None) -> str:
    if not ab or not ab.get("available"):
        return "UNPROVEN"
    return str(ab.get("status") or "UNPROVEN")


def _row(
    module: str,
    *,
    samples: int,
    t5: float | None,
    t10: float | None,
    t20: float | None,
    incremental: float | None,
    cost: float | None,
    efficiency: float | None,
    status: str,
) -> dict[str, Any]:
    return {
        "module": module,
        "samples": samples,
        "t5_alpha": t5,
        "t10_alpha": t10,
        "t20_alpha": t20,
        "incremental_alpha": incremental,
        "cost_usd": cost,
        "efficiency": efficiency,
        "status": status,
    }


def build_alpha_lab(cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    from ashare.services.research import latest_research

    cfg = cfg or {}
    data = latest_research(cfg) or {}
    pack = data.get("research_outcomes") or {}
    rows: list[dict[str, Any]] = []

    # Signal attribution by primary source
    sig = pack.get("signal_attribution") or {}
    for src, horizons in (sig.get("by_primary_source") or {}).items():
        if src == "unknown":
            continue
        h5 = (horizons.get("5") or {})
        h10 = (horizons.get("10") or {})
        h20 = (horizons.get("20") or {})
        n = (h5.get("sample_count") or 0) if not h5.get("insufficient_sample") else 0
        sel5 = ((h5.get("selection_alpha") or {}).get("mean") if not h5.get("insufficient_sample") else None)
        sel10 = ((h10.get("selection_alpha") or {}).get("mean") if not h10.get("insufficient_sample") else None)
        sel20 = ((h20.get("selection_alpha") or {}).get("mean") if not h20.get("insufficient_sample") else None)
        st = "STRONG" if sel5 and sel5 > 0.02 else ("WEAK" if sel5 and sel5 > 0 else "UNPROVEN")
        rows.append(_row(src.capitalize(), samples=n, t5=sel5, t10=sel10, t20=sel20, incremental=None, cost=0, efficiency=None, status=st))

    # AI Council ablation
    ab = pack.get("ai_council_ablation") or {}
    if ab.get("available"):
        hz = ab.get("horizons") or {}
        h5 = hz.get("5") or {}
        h10 = hz.get("10") or {}
        h20 = hz.get("20") or {}
        rows.append(
            _row(
                "AI",
                samples=h5.get("sample_count") or 0,
                t5=(h5.get("with_council") or {}).get("mean"),
                t10=(h10.get("with_council") or {}).get("mean"),
                t20=(h20.get("with_council") or {}).get("mean"),
                incremental=h5.get("ai_incremental_alpha"),
                cost=ab.get("llm_cost_usd"),
                efficiency=ab.get("ai_efficiency"),
                status=_status_from_ablation(ab),
            )
        )

    # ML weight experiment summary
    try:
        from ashare.ml.weight_experiment import list_weight_experiments

        exps = list_weight_experiments(cfg, limit=1)
        if exps:
            e = exps[-1]
            rows.append(
                _row(
                    "ML",
                    samples=int(e.get("n_folds") or 0),
                    t5=e.get("best_mean_ic"),
                    t10=None,
                    t20=None,
                    incremental=e.get("best_delta"),
                    cost=0,
                    efficiency=None,
                    status="WEAK" if (e.get("best_delta") or 0) < 0.002 else "STRONG",
                )
            )
    except Exception:  # noqa: BLE001
        pass

    # Notification attribution
    try:
        from ashare.notification.outcome import refresh_notification_outcomes

        nop = refresh_notification_outcomes(cfg)
        nattr = nop.get("notification_attribution") or {}
        for level in ("BUY", "STRONG_BUY"):
            h5 = (nattr.get(level) or {}).get("5") or {}
            if h5.get("insufficient_sample"):
                continue
            rows.append(
                _row(
                    f"Notify_{level}",
                    samples=h5.get("sample_count") or 0,
                    t5=h5.get("mean_market_alpha"),
                    t10=((nattr.get(level) or {}).get("10") or {}).get("mean_market_alpha"),
                    t20=((nattr.get(level) or {}).get("20") or {}).get("mean_market_alpha"),
                    incremental=None,
                    cost=0,
                    efficiency=None,
                    status="STRONG",
                )
            )
    except Exception:  # noqa: BLE001
        pass

    # Factor report
    root = Path(cfg.get("_root") or Path(__file__).resolve().parents[2])
    factor_path = root / "data" / "alpha" / "factor_report.json"
    if factor_path.exists():
        try:
            fr = json.loads(factor_path.read_text(encoding="utf-8"))
            for rc in fr.get("retire_candidates") or []:
                rows.append(
                    _row(
                        f"Factor_{rc.get('factor')}",
                        samples=rc.get("sample_note") or 0,
                        t5=None,
                        t10=rc.get("t10_top_bottom_spread"),
                        t20=None,
                        incremental=None,
                        cost=0,
                        efficiency=None,
                        status="RETIRE_CANDIDATE",
                    )
                )
        except Exception:  # noqa: BLE001
            pass

    return {
        "available": bool(rows),
        "as_of": data.get("as_of"),
        "modules": rows,
        "calibration": pack.get("calibration"),
        "ai_council_ablation": ab,
        "signal_attribution": sig,
        "notification_llm_cost": 0,
    }
