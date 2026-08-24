from __future__ import annotations

"""Exit Engine — orchestrates features + heuristic (+ optional ML). Signals only."""

from datetime import date, datetime, timezone
from typing import Any

import pandas as pd

from ashare.portfolio.exit.config import load_exit_config
from ashare.portfolio.exit.features import compute_exit_features
from ashare.portfolio.exit.heuristic import REASON_ZH, compute_exit_score, top_reason_texts
from ashare.portfolio.exit.thesis_decay import evaluate_thesis_decay


class ExitEngine:
    def __init__(self, cfg: dict[str, Any] | None = None) -> None:
        self.cfg = cfg or {}
        self.exit_cfg = load_exit_config(self.cfg)

    @property
    def enabled(self) -> bool:
        return bool(self.exit_cfg.get("enabled", True))

    def evaluate(
        self,
        *,
        symbol: str,
        bars: pd.DataFrame | None,
        as_of: date | str | None = None,
        position: dict[str, Any] | None = None,
        news: dict[str, Any] | None = None,
        event: dict[str, Any] | None = None,
        portfolio: dict[str, Any] | None = None,
        ml_expected: dict[str, Any] | None = None,
        benchmark_bars: pd.DataFrame | None = None,
        buy_thesis: dict[str, Any] | None = None,
        current_thesis: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self.enabled:
            return {"available": False, "action": "HOLD", "note": "exit_engine_disabled", "symbol": symbol}

        as_of_d = as_of or date.today()
        pos = {"symbol": symbol, **(position or {})}
        feat = compute_exit_features(
            bars=bars,
            as_of=as_of_d,
            position=pos,
            news=news,
            event=event,
            portfolio=portfolio,
            ml_expected=ml_expected,
            benchmark_bars=benchmark_bars,
            cfg=self.cfg,
        )
        score_pack = compute_exit_score(feat, self.cfg)

        # Optional ML overlay
        mode = str(self.exit_cfg.get("mode") or "heuristic").lower()
        ml_pack = None
        if mode in {"ml", "hybrid"}:
            from ashare.portfolio.exit.ml_exit import predict_exit_ml

            ml_pack = predict_exit_ml(feat, self.cfg)
            if ml_pack.get("available") and mode == "ml":
                score_pack = {
                    **score_pack,
                    "exit_score": ml_pack["exit_score"],
                    "action": ml_pack["action"],
                    "mode": "MODEL",
                    "confidence": ml_pack.get("confidence", score_pack.get("confidence")),
                    "ml": ml_pack,
                }
            elif ml_pack.get("available") and mode == "hybrid":
                blended = 0.6 * float(score_pack["exit_score"]) + 0.4 * float(ml_pack["exit_score"])
                from ashare.portfolio.exit.config import soft_action

                score_pack = {
                    **score_pack,
                    "exit_score": round(blended, 4),
                    "action": soft_action(blended, self.exit_cfg.get("thresholds")),
                    "mode": "HYBRID",
                    "ml": ml_pack,
                }
            else:
                score_pack["ml"] = ml_pack or {"available": False, "note": "INSUFFICIENT_SAMPLE"}

        # Expected returns: heuristic mapping from exit_score (not fabricated ML)
        er = _heuristic_expected_returns(float(score_pack.get("exit_score") or 0), ml_expected)

        thesis = evaluate_thesis_decay(buy_thesis=buy_thesis, current=current_thesis or _thesis_from_context(news, event, feat))
        if thesis.get("available") and thesis.get("level") == "HIGH" and float(score_pack.get("exit_score") or 0) < 0.6:
            # thesis decay informs reasons — does NOT silently raise score beyond soft bump
            score_pack = dict(score_pack)
            score_pack["exit_score"] = round(min(1.0, float(score_pack["exit_score"]) + 0.08), 4)
            from ashare.portfolio.exit.config import soft_action

            score_pack["action"] = soft_action(score_pack["exit_score"], self.exit_cfg.get("thresholds"))
            reasons = list(score_pack.get("reasons") or [])
            if "thesis_decay" not in reasons:
                reasons = ["thesis_decay", *reasons][:5]
            score_pack["reasons"] = reasons

        reasons = list(score_pack.get("reasons") or [])
        return {
            "symbol": symbol,
            "as_of": feat.get("as_of"),
            "signal_time": datetime.now(timezone.utc).isoformat(),
            "exit_score": score_pack.get("exit_score"),
            "action": score_pack.get("action"),
            "confidence": score_pack.get("confidence"),
            "expected_return_1d": er.get("1"),
            "expected_return_5d": er.get("5"),
            "expected_return_10d": er.get("10"),
            "expected_return_20d": er.get("20"),
            "expected_return_source": er.get("source"),
            "reasons": reasons,
            "reason_texts": top_reason_texts(reasons),
            "reason_details": score_pack.get("reason_details"),
            "exit_types": score_pack.get("exit_types"),
            "mode": score_pack.get("mode"),
            "features": feat.get("features"),
            "n_features_available": feat.get("n_available"),
            "current_price": feat.get("current_price"),
            "entry_price": feat.get("entry_price"),
            "hold_days": feat.get("hold_days"),
            "unrealized_return": feat.get("unrealized_return"),
            "max_favorable_return": feat.get("max_favorable_return"),
            "giveback": feat.get("giveback"),
            "event_state": feat.get("event_state"),
            "thesis_decay": thesis,
            "atr": feat.get("atr"),
            "trailing_stop": _trailing_stop(feat, self.exit_cfg),
            "versions": {
                "exit_version": self.exit_cfg.get("version") or "exit_v1",
                "factor_version": "factor_v1",
                "model_version": (score_pack.get("ml") or {}).get("model_version"),
            },
            "available": bool(score_pack.get("available")),
            "note": score_pack.get("note"),
        }


def _heuristic_expected_returns(exit_score: float, ml_expected: dict[str, Any] | None) -> dict[str, Any]:
    ml = ml_expected or {}
    if ml.get("available"):
        return {
            "1": ml.get("expected_return_1d"),
            "5": ml.get("expected_return_5d"),
            "10": ml.get("expected_return_10d"),
            "20": ml.get("expected_return_20d"),
            "source": "MODEL",
        }
    # Heuristic: map exit_score to mild negative expected returns (documented as HEURISTIC)
    s = max(0.0, min(1.0, exit_score))
    return {
        "1": round(-0.002 * s, 6),
        "5": round(-0.012 * s, 6),
        "10": round(-0.022 * s, 6),
        "20": round(-0.035 * s, 6),
        "source": "HEURISTIC",
    }


def _trailing_stop(feat: dict[str, Any], exit_cfg: dict[str, Any]) -> dict[str, Any]:
    tr = dict(exit_cfg.get("trailing_atr") or {})
    if not tr.get("enabled", True):
        return {"available": False, "note": "disabled"}
    atr = feat.get("atr")
    px = feat.get("current_price")
    peak = None
    # peak from giveback path
    if feat.get("max_favorable_return") is not None and feat.get("entry_price"):
        peak = float(feat["entry_price"]) * (1.0 + float(feat["max_favorable_return"]))
    if atr is None or px is None or peak is None:
        return {"available": False, "note": "atr_or_peak_unavailable"}
    mult = float(tr.get("multiplier", 2.5))
    stop = peak - mult * float(atr)
    triggered = float(px) < stop
    return {
        "available": True,
        "stop_price": round(stop, 4),
        "triggered": triggered,
        "type": "RISK_EXIT",
        "note": "ATR trailing — risk only, does not replace Exit Engine",
    }


def _thesis_from_context(news: dict[str, Any] | None, event: dict[str, Any] | None, feat: dict[str, Any]) -> dict[str, Any]:
    news = news or {}
    event = event or {}
    mom = (feat.get("features") or {}).get("momentum_decay") or {}
    return {
        "news_direction": news.get("direction") or news.get("current_direction"),
        "event_state": event.get("event_state") or event.get("state") or feat.get("event_state"),
        "momentum": -float(mom["value"]) if mom.get("available") else None,
        "profit_state": "ACTIVE" if (feat.get("unrealized_return") or 0) > 0 else "WEAKENING",
    }


def evaluate_position(**kwargs: Any) -> dict[str, Any]:
    cfg = kwargs.pop("cfg", None)
    return ExitEngine(cfg).evaluate(**kwargs)


def evaluate_book(
    positions: list[dict[str, Any]],
    *,
    bars_by_symbol: dict[str, pd.DataFrame],
    cfg: dict[str, Any] | None = None,
    as_of: date | str | None = None,
    context_by_symbol: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    engine = ExitEngine(cfg)
    ctx = context_by_symbol or {}
    rows = []
    for p in positions:
        sym = str(p.get("symbol") or "")
        c = ctx.get(sym) or {}
        rows.append(
            engine.evaluate(
                symbol=sym,
                bars=bars_by_symbol.get(sym),
                as_of=as_of,
                position=p,
                news=c.get("news"),
                event=c.get("event"),
                portfolio=c.get("portfolio"),
                ml_expected=c.get("ml_expected"),
                benchmark_bars=c.get("benchmark_bars"),
                buy_thesis=c.get("buy_thesis"),
                current_thesis=c.get("current_thesis"),
            )
        )
    return {
        "as_of": str(as_of or date.today()),
        "n": len(rows),
        "signals": rows,
        "counts": {
            "HOLD": sum(1 for r in rows if r.get("action") == "HOLD"),
            "REDUCE": sum(1 for r in rows if r.get("action") == "REDUCE"),
            "EXIT": sum(1 for r in rows if r.get("action") == "EXIT"),
        },
    }


# export for UI
REASON_LABELS = REASON_ZH
