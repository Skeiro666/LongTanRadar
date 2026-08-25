from __future__ import annotations

import logging
from typing import Any

from ashare.ai.client import LLMClient, parse_json_object
from ashare.news.entity_resolve import entities_from_llm_guesses
from ashare.news.models import NewsEntity, RawNews

logger = logging.getLogger("ashare.news.llm_mapping")


class MappingTimeout(TimeoutError):
    """Local Ollama mapping timed out — caller should skip remaining mapping this cycle."""


def _is_timeout(exc: BaseException) -> bool:
    blob = f"{type(exc).__name__} {exc}".lower()
    return "timeout" in blob or "timed out" in blob


_SYSTEM = """你是 A 股新闻实体映射助手（本地新闻智能引擎）。
根据标题和摘要，推断最可能受益或相关的 A 股上市公司。
硬规则：
1. 只输出一个 JSON 对象，包含 beneficiaries 数组。
2. 每项字段：symbol（如 600519.SH）、name、confidence（0~0.45，不得超过 0.45）。
3. 不确定则 beneficiaries 为空数组；禁止编造代码。
4. 只映射 A 股，不要港股/美股。
5. 禁止 BUY/SELL/仓位。"""


def infer_entities_from_news(
    news: RawNews,
    client: LLMClient,
    *,
    max_guesses: int = 3,
) -> list[NewsEntity]:
    """Task A only: entity resolution fallback. Does not extract intelligence or emit BUY."""
    if not client.configured:
        return []
    summary = (news.summary or news.content or "")[:400]
    user = (
        f"标题：{news.title}\n"
        f"摘要：{summary}\n\n"
        "请输出 JSON：{\"beneficiaries\": [{\"symbol\": \"...\", \"name\": \"...\", \"confidence\": 0.3}]}"
    )
    try:
        raw = client.chat(
            _SYSTEM,
            user,
            json_mode=True,
            call_site="news_llm_mapping",
            max_tokens=512,
        )
        data = parse_json_object(raw)
        guesses = list(data.get("beneficiaries") or data.get("stocks") or [])[:max_guesses]
        return entities_from_llm_guesses(news, guesses)
    except Exception as exc:  # noqa: BLE001
        logger.warning("news llm mapping failed for %s: %s", news.id, exc)
        if _is_timeout(exc):
            raise MappingTimeout(str(exc)) from exc
        return []


def news_llm_client(cfg: dict[str, Any]):
    import os

    # Unit tests must not fan out to a live Ollama (60s timeouts). Inject FakeNewsClient instead.
    if os.getenv("PYTEST_CURRENT_TEST") and str(os.getenv("NEWS_AI_TEST_LIVE") or "").strip().lower() not in {
        "1",
        "true",
        "yes",
        "on",
    }:
        extra = (cfg or {}).get("news") or {}
        if extra.get("_test_client") is not None:
            return extra["_test_client"]
        return None

    from ashare.ai.client import client_for_news

    return client_for_news(cfg)
