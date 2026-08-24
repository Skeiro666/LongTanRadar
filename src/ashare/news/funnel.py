from __future__ import annotations

from ashare.news.classify import classify_news
from ashare.news.models import RawNews
from ashare.news.schema import HIGH_VALUE_CLASSIFICATIONS
from ashare.news.score import source_quality


_TITLE_HINTS = ("公告", "预增", "预减", "重大合同", "中标", "立案", "减持", "回购", "并购", "重组")


def is_high_value_news(news: RawNews, classification: str | None = None) -> bool:
    """Rule filter before Local LLM. Do not send every headline to Ollama."""
    cat = classification or classify_news(news)
    if cat in HIGH_VALUE_CLASSIFICATIONS:
        return True
    q = source_quality(news)
    if q in {"A", "B"}:
        return True
    title = news.title or ""
    return any(h in title for h in _TITLE_HINTS)
