from __future__ import annotations

import json
from pathlib import Path

from ashare.news.intel_cache import NewsIntelCache
from ashare.news.intelligence import LocalNewsIntelligence
from ashare.news.models import RawNews, make_id, title_hash


class FakeNewsClient:
    configured = True
    model = "qwen3.5:4b"

    def __init__(self, *, intel: dict | None = None, fail: str | None = None) -> None:
        self.calls = 0
        self.intel = intel or {
            "event_type": "order",
            "direction": "positive",
            "importance": 0.8,
            "novelty": 0.7,
            "market_relevance": 0.75,
            "impact_horizon": "medium",
            "event_confidence": 0.9,
            "summary": "公司签订重大合同",
            "evidence": ["签订重大合同订单金额10亿"],
            "hypothesis": "",
            "beneficiary_industries": [],
        }
        self.fail = fail

    def chat(self, system: str, user: str, **kwargs) -> str:
        self.calls += 1
        if self.fail == "raise":
            raise RuntimeError("ollama down")
        if self.fail == "json":
            return "not-json"
        if "beneficiaries" in system or "实体映射" in system:
            return json.dumps(
                {"beneficiaries": [{"symbol": "000786.SZ", "name": "北新建材", "confidence": 0.4}]}
            )
        return json.dumps(self.intel, ensure_ascii=False)


def sample_news(title: str, **kw) -> RawNews:
    return RawNews(
        id=kw.get("id") or make_id("N"),
        source="sina",
        title=title,
        fetched_at="2026-08-20T10:00:00+00:00",
        summary=kw.get("summary", title),
        published_at=kw.get("published_at", "2026-08-20 10:00:00"),
        title_hash=title_hash(title),
        media=kw.get("media", "新浪财经"),
    )


def make_engine(tmp_path: Path, client: FakeNewsClient | None, **intel_cfg) -> LocalNewsIntelligence:
    cfg = {
        "_root": str(tmp_path),
        "news": {
            "llm": {"model": "qwen3.5:4b", "base_url": "http://127.0.0.1:11434/v1"},
            "intelligence": {"max_concurrency": 1, "max_retries": 0, **intel_cfg},
        },
    }
    cache = NewsIntelCache(tmp_path)
    return LocalNewsIntelligence(cfg, client, cache=cache)
