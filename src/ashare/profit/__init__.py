from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ProfitInflectionResult:
    symbol: str
    score: float
    quality: str  # A|B|C|D|unavailable
    reason: str
    components: dict[str, float] = field(default_factory=dict)
    available: bool = False


class ProfitInflectionEngine:
    """
    Structural profit-gap detector.

    Without as-of financial time series, we only score from forecast/event meta
    (AkShare 业绩预告). Financial sequence acceleration remains an interface
    returning available=False — never fabricate ROE/cashflow.
    """

    def __init__(self, cfg: dict[str, Any] | None = None) -> None:
        self.cfg = cfg or {}
        self.fundamentals_available = False

    def score_from_forecast_meta(self, row: dict[str, Any]) -> ProfitInflectionResult:
        sym = str(row.get("symbol") or "")
        yoy = float(row.get("yoy_pct") or row.get("profit_gap_score") or 0.0)
        # profit_gap_score in pool is often 0-3 scale; yoy_pct may be percent
        if abs(yoy) > 10:
            growth = yoy / 100.0
        else:
            growth = yoy
        ftype = str(row.get("forecast_type") or "")
        tags = [str(t) for t in (row.get("event_tags") or [])]

        bad = any(x in ftype for x in ("预减", "首亏", "续亏", "略减", "下降"))
        one_off = any(x in "".join(tags) + ftype for x in ("一次性", "非经常", "补贴"))

        accel = max(0.0, growth - 0.15)  # proxy vs soft baseline 15%
        surprise = min(1.0, max(0.0, growth))
        margin = 0.0  # unavailable
        cash = 0.0  # unavailable

        if bad:
            quality = "D"
            score = -min(1.0, abs(growth))
            reason = f"负面预告类型={ftype or tags}"
        elif one_off:
            quality = "D"
            score = min(0.3, surprise * 0.3)
            reason = "疑似一次性收益相关表述，降权"
        elif growth >= 0.3:
            quality = "C"  # profit-only without revenue/cash confirmation
            score = min(1.0, 0.4 + accel)
            reason = f"预告利润高增代理 growth≈{growth:.0%}（缺收入/现金流确认→最高C）"
        elif growth > 0:
            quality = "C"
            score = min(0.6, 0.2 + growth)
            reason = f"预告正增长 growth≈{growth:.0%}"
        else:
            quality = "unavailable" if not (ftype or tags) else "C"
            score = 0.0
            reason = "无有效利润断层信号"

        # A/B require revenue+cash — not available
        return ProfitInflectionResult(
            symbol=sym,
            score=float(score),
            quality=quality,
            reason=reason,
            components={
                "profit_growth_proxy": growth,
                "profit_growth_acceleration": accel,
                "revenue_growth_acceleration": margin,
                "margin_expansion": margin,
                "earnings_surprise": surprise,
                "cashflow_confirmation": cash,
            },
            available=bool(ftype or tags or abs(growth) > 0),
        )

    def score_from_financials(self, _symbol: str, _quarters: list[dict[str, Any]]) -> ProfitInflectionResult:
        return ProfitInflectionResult(
            symbol=_symbol,
            score=0.0,
            quality="unavailable",
            reason="as-of 财务报表未接入，拒绝伪造",
            available=False,
        )

    def enrich_candidates(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out = []
        for r in rows:
            pi = self.score_from_forecast_meta(r)
            item = dict(r)
            item["profit_inflection"] = {
                "score": pi.score,
                "quality": pi.quality,
                "reason": pi.reason,
                "components": pi.components,
                "available": pi.available,
            }
            # D 类不得进入高优先级
            item["profit_inflection_priority"] = 0 if pi.quality == "D" else (1 if pi.available else 0)
            out.append(item)
        return out
