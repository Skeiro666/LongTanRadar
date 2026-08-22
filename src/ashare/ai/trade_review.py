from __future__ import annotations

import json
import logging
from typing import Any

import pandas as pd

from ashare.ai.client import client_from_cfg, parse_json_object
from ashare.data.provider import ensure_panel
from ashare.symbols import to_symbol

logger = logging.getLogger("ashare.ai.trade_review")

SYSTEM = """你是 A 股交易风控审查员。量化模型已给出候选买入名单，你必须结合 K 线结构与近期新闻决定「批准买入」或「拒绝」。
硬规则：
1. 只输出一个 JSON 对象，不要 Markdown。
2. 破位下跌、放量大阴、业绩暴雷/立案/退市风险 → 倾向拒绝。
3. 健康回调、消息中性偏利好、结构未坏 → 可批准。
4. 新闻不足时，以 K 线结构为准，宁可拒绝也不要猜测利好。
5. 不要承诺收益，不要荐股话术。

输出格式：
{
  "decisions": [
    {
      "symbol": "000786.SZ",
      "approve": true/false,
      "confidence": 0.0到1.0,
      "rationale": "中文简短理由（看了K线与新闻的哪一点）"
    }
  ],
  "summary": "本轮审查一句话"
}
"""


def _strip_em(text: str) -> str:
    import re

    return re.sub(r"</?em>", "", text or "").strip()


def fetch_stock_news(symbol: str, limit: int = 6) -> list[dict[str, str]]:
    """Compatibility wrapper → News Intelligence Engine (multi-source)."""
    try:
        from ashare.news.engine import NewsIntelligenceEngine

        pkg = NewsIntelligenceEngine({}).collect_stock(symbol, persist=False)
        heads = list(pkg.get("legacy_headlines") or [])[: int(limit)]
        return heads
    except Exception as exc:  # noqa: BLE001
        logger.warning("news fetch failed %s: %s", symbol, exc)
        return []


def kline_summary(df: pd.DataFrame, lookback: int = 30) -> dict[str, Any]:
    if df is None or df.empty:
        return {}
    sub = df.sort_values("date").tail(lookback).copy()
    c = sub["close"].astype(float)
    last = float(c.iloc[-1])
    ma20 = float(c.tail(20).mean()) if len(c) >= 20 else float(c.mean())
    ma60 = float(c.tail(min(60, len(c))).mean())
    bars = []
    for _, row in sub.tail(10).iterrows():
        bars.append(
            {
                "date": str(pd.to_datetime(row["date"]).date()),
                "o": round(float(row["open"]), 2),
                "h": round(float(row["high"]), 2),
                "l": round(float(row["low"]), 2),
                "c": round(float(row["close"]), 2),
                "pct": round(float(row.get("pct_chg") or 0), 2),
            }
        )
    return {
        "last_close": round(last, 2),
        "ma20": round(ma20, 2),
        "ma60": round(ma60, 2),
        "gap_ma20_pct": round((last / ma20 - 1.0) * 100, 2) if ma20 else None,
        "gap_ma60_pct": round((last / ma60 - 1.0) * 100, 2) if ma60 else None,
        "ret_1d_pct": round(float(c.pct_change().iloc[-1]) * 100, 2),
        "ret_5d_pct": round(float(c.iloc[-1] / c.iloc[-6] - 1.0) * 100, 2) if len(c) >= 6 else None,
        "ret_20d_pct": round(float(c.iloc[-1] / c.iloc[-21] - 1.0) * 100, 2) if len(c) >= 21 else None,
        "from_20d_high_pct": round(float(last / c.tail(20).max() - 1.0) * 100, 2),
        "recent_bars": bars,
    }


def _heuristic_review(payload: dict[str, Any]) -> dict[str, Any]:
    """If LLM down: reject dump/breakdown, else approve cautiously."""
    decisions = []
    for item in payload.get("candidates") or []:
        k = item.get("kline") or {}
        ret1 = float(k.get("ret_1d_pct") or 0)
        gap60 = float(k.get("gap_ma60_pct") or 0)
        from_hi = float(k.get("from_20d_high_pct") or 0)
        approve = True
        reasons = []
        if ret1 <= -4:
            approve = False
            reasons.append(f"当日大跌{ret1:.1f}%")
        if gap60 < 0 and from_hi < -12:
            approve = False
            reasons.append("相对高点回撤深且在MA60下，疑似破位")
        news = item.get("news") or []
        bad_kw = ("暴雷", "立案", "退市", "亏损", "下降", "减持", "处罚", "警示")
        hits = [n.get("title", "") for n in news if any(k in (n.get("title") or "") for k in bad_kw)]
        if hits:
            approve = False
            reasons.append("新闻偏负面: " + hits[0][:40])
        if approve:
            reasons.append("启发式：未见明显破位/暴雷，谨慎通过")
        decisions.append(
            {
                "symbol": item.get("symbol"),
                "approve": approve,
                "confidence": 0.45,
                "rationale": "；".join(reasons),
                "source": "heuristic",
            }
        )
    return {"decisions": decisions, "summary": "LLM不可用，规则审查", "source": "heuristic"}


def build_review_payload(cfg: dict[str, Any], picks: list[dict[str, Any]]) -> dict[str, Any]:
    symbols = [to_symbol(p["symbol"]) for p in picks if p.get("symbol")]
    panel = ensure_panel(cfg, symbols) if symbols else {}
    candidates = []
    for p in picks:
        sym = to_symbol(p["symbol"])
        df = panel.get(sym)
        candidates.append(
            {
                "symbol": sym,
                "name": p.get("name") or "",
                "quant": {
                    "score": p.get("score"),
                    "ml_score": p.get("ml_score"),
                    "value_score": p.get("value_score"),
                    "ml_z": p.get("ml_z"),
                    "mr_z": p.get("mr_z"),
                    "agreement": p.get("agreement"),
                    "why": p.get("why"),
                    "close": p.get("close"),
                    "weight": p.get("weight"),
                },
                "kline": kline_summary(df) if df is not None else {},
                "news": fetch_stock_news(sym, limit=5),
            }
        )
    return {"candidates": candidates}


def review_trade_candidates(cfg: dict[str, Any], picks: list[dict[str, Any]]) -> dict[str, Any]:
    """
    AI gate: returns {approved: [...picks], rejected: [...], reviews: [...], source}
    Default: reject on LLM failure only for dump-like; see heuristic.
    """
    ai_cfg = cfg.get("ai") or {}
    if not bool(ai_cfg.get("trade_review", True)):
        return {
            "approved": list(picks),
            "rejected": [],
            "reviews": [],
            "source": "disabled",
            "summary": "AI 审查已关闭，按量化结果买入",
        }
    if not picks:
        return {"approved": [], "rejected": [], "reviews": [], "source": "empty", "summary": "无候选"}

    payload = build_review_payload(cfg, picks)
    client = client_from_cfg(cfg)
    raw_decision: dict[str, Any]
    if client.configured:
        try:
            text = client.chat(
                SYSTEM,
                json.dumps(payload, ensure_ascii=False, default=str)[:12000],
                json_mode=True,
                role="trade_review",
                call_site="trade.review",
            )
            raw_decision = parse_json_object(text)
            raw_decision["source"] = "llm"
        except Exception as exc:  # noqa: BLE001
            logger.warning("LLM trade review failed: %s", exc)
            raw_decision = _heuristic_review(payload)
            raw_decision["llm_error"] = str(exc)[:200]
    else:
        raw_decision = _heuristic_review(payload)

    by_sym = {to_symbol(d.get("symbol")): d for d in (raw_decision.get("decisions") or []) if d.get("symbol")}
    approved: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    reviews: list[dict[str, Any]] = []
    for p in picks:
        sym = to_symbol(p["symbol"])
        d = by_sym.get(sym) or {"approve": False, "rationale": "审查结果缺失，默认拒绝", "confidence": 0.0}
        # fail-closed if LLM omitted a name
        approve = bool(d.get("approve"))
        item = {
            **p,
            "ai_approve": approve,
            "ai_confidence": d.get("confidence"),
            "ai_rationale": d.get("rationale") or "",
            "ai_source": raw_decision.get("source"),
        }
        reviews.append(item)
        if approve:
            approved.append(item)
        else:
            rejected.append(item)

    return {
        "approved": approved,
        "rejected": rejected,
        "reviews": reviews,
        "source": raw_decision.get("source"),
        "summary": raw_decision.get("summary") or "",
        "llm_error": raw_decision.get("llm_error"),
        "payload_preview": [
            {
                "symbol": c["symbol"],
                "name": c.get("name"),
                "kline": {k: (c.get("kline") or {}).get(k) for k in ("last_close", "ret_1d_pct", "gap_ma20_pct", "from_20d_high_pct")},
                "news_titles": [n.get("title") for n in (c.get("news") or [])[:3]],
            }
            for c in payload.get("candidates") or []
        ],
    }
