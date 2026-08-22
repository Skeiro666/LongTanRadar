from __future__ import annotations

import json
import logging
from pathlib import Path

from ashare.ai.client import client_from_cfg, parse_json_object
from ashare.ai.features import snapshot_features
from ashare.models import OrderIntent
from ashare.strategy.base import Strategy, StrategyContext, intents_from_weights
from ashare.strategy.multi_factor import MultiFactorStrategy
from ashare.symbols import to_symbol

logger = logging.getLogger("ashare.strategy.ai_select")

SYSTEM = (
    "你是 A 股量化选股助手。只能从给定股票里挑多头，禁止推荐池外代码。"
    "遵守：不买 ST/停牌/涨停；普通账户不能做空。等权持有。"
    "只输出 JSON：{\"picks\":[\"600519.SH\",...],\"reason\":\"一句话\"}"
)


class AISelectStrategy(Strategy):
    """Month-end LLM picks from a factor snapshot; cached; falls back to multi-factor."""

    def __init__(
        self,
        cfg: dict,
        top_n: int = 5,
        max_name_weight: float = 0.20,
        max_gross_weight: float = 0.95,
        rebalance_threshold: float = 0.05,
        lookback_mom: int = 20,
        lookback_vol: int = 20,
        lookback_value: int = 60,
    ) -> None:
        self.cfg = cfg
        self.top_n = int(top_n)
        self.max_name_weight = float(max_name_weight)
        self.max_gross_weight = float(max_gross_weight)
        self.rebalance_threshold = float(rebalance_threshold)
        self.lookback_mom = int(lookback_mom)
        self.lookback_vol = int(lookback_vol)
        self.lookback_value = int(lookback_value)
        self._fallback = MultiFactorStrategy(
            lookback_mom=lookback_mom,
            lookback_vol=lookback_vol,
            lookback_value=lookback_value,
            top_n=top_n,
            max_name_weight=max_name_weight,
            max_gross_weight=max_gross_weight,
            rebalance_threshold=rebalance_threshold,
        )
        cache = cfg.get("ai", {}).get("cache_dir", "data/cache/ai_decisions")
        self.cache_dir = Path(cache)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def on_date(self, ctx: StrategyContext) -> list[OrderIntent]:
        ctx.rebalance_threshold = self.rebalance_threshold
        if not ctx.is_month_end:
            return []
        features = snapshot_features(ctx, self.lookback_mom, self.lookback_vol, self.lookback_value)
        allowed = {to_symbol(r["symbol"]) for r in features}
        picks = self._picks(ctx, features, allowed)
        if not picks:
            logger.info("AI picks empty, fallback multi_factor on %s", ctx.as_of)
            return self._fallback.on_date(ctx)
        raw = 1.0 / len(picks)
        w = min(raw, self.max_name_weight)
        weights = {s: w for s in picks}
        gross = sum(weights.values())
        if gross > self.max_gross_weight:
            scale = self.max_gross_weight / gross
            weights = {k: v * scale for k, v in weights.items()}
        return intents_from_weights(ctx, weights, reason="ai_select")

    def _picks(self, ctx: StrategyContext, features: list[dict], allowed: set[str]) -> list[str]:
        path = self.cache_dir / f"{ctx.as_of.isoformat()}.json"
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                return self._sanitize(data.get("picks") or [], allowed)
            except Exception:  # noqa: BLE001
                pass
        client = client_from_cfg(self.cfg)
        if not client.configured or not self.cfg.get("ai", {}).get("enabled", True):
            return []
        user = (
            f"日期 {ctx.as_of.isoformat()}，最多选 {self.top_n} 只。"
            f"候选（已滤 ST/停牌）:\n{json.dumps(features, ensure_ascii=False)}"
        )
        try:
            text = client.chat(SYSTEM, user, json_mode=True)
            data = parse_json_object(text)
        except Exception as exc:  # noqa: BLE001
            logger.warning("AI select failed: %s", exc)
            return []
        picks = self._sanitize(data.get("picks") or [], allowed)[: self.top_n]
        path.write_text(
            json.dumps({"picks": picks, "reason": data.get("reason", ""), "raw": data}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return picks

    def _sanitize(self, picks: list, allowed: set[str]) -> list[str]:
        out: list[str] = []
        for p in picks:
            sym = to_symbol(str(p))
            if sym in allowed and sym not in out:
                out.append(sym)
        return out[: self.top_n]
