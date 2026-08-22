from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ashare.ai.client import LLMClient, client_from_cfg

logger = logging.getLogger("ashare.ai.review")

SYSTEM = (
    "你是 A 股量化研究员。根据回测指标做简短复盘："
    "说明策略类型、收益是否可能来自过拟合、回撤与换手是否可接受、"
    "以及下一步该改数据/规则还是改因子。不要给出荐股或承诺收益。"
    "用中文，分条，不超过 400 字。"
)


def review_backtest(cfg: dict[str, Any], metrics: dict[str, Any]) -> str | None:
    ai = cfg.get("ai", {})
    if not ai.get("enabled", True) or not ai.get("review_backtest", True):
        return None
    client = client_from_cfg(cfg)
    if not client.configured:
        logger.info("Skip AI review: AI_API_KEY not set")
        return None
    slim = {
        k: metrics.get(k)
        for k in (
            "initial_balance",
            "final_equity",
            "total_return",
            "annualized",
            "max_drawdown",
            "sharpe",
            "turnover",
            "win_rate",
            "trades",
            "yearly",
        )
    }
    slim["strategy"] = cfg.get("strategy", {}).get("name")
    slim["execute_at"] = cfg.get("trading", {}).get("execute_at")
    try:
        text = client.chat(SYSTEM, f"回测摘要 JSON:\n{slim}")
    except Exception as exc:  # noqa: BLE001
        logger.warning("AI review failed: %s", exc)
        return None
    out = Path(cfg["_root"]) / "data" / "ai_review.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text.strip() + "\n", encoding="utf-8")
    return text.strip()
