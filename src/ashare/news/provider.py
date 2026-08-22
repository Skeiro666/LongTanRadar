from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from ashare.news.models import RawNews


class NewsProvider(ABC):
    """Abstract news/announcement/policy source. Research must not import Eastmoney directly."""

    name: str = "base"
    version: str = "v1"

    @abstractmethod
    def fetch_latest_news(self, limit: int = 20) -> list[RawNews]:
        ...

    @abstractmethod
    def fetch_stock_news(self, symbol: str, *, name: str = "", limit: int = 20) -> list[RawNews]:
        ...

    def fetch_announcement(self, symbol: str, *, limit: int = 20) -> list[RawNews]:
        return []

    def fetch_policy_news(self, *, limit: int = 20) -> list[RawNews]:
        return []


class ProviderUnavailable(RuntimeError):
    def __init__(self, provider: str, detail: str = "") -> None:
        self.provider = provider
        self.status = "PROVIDER_UNAVAILABLE"
        super().__init__(detail or provider)
