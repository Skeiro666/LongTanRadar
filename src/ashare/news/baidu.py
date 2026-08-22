from __future__ import annotations

import logging
from typing import Any

import requests

from ashare.news.common import row_to_news, unix_to_iso
from ashare.news.provider import NewsProvider, ProviderUnavailable
from ashare.symbols import bare_code

logger = logging.getLogger("ashare.news.baidu")


class BaiduFinanceProvider(NewsProvider):
    """Baidu Gushitong aggregates 同花顺 / 东财 / 证券时报等，不绑死单一站点。"""

    name = "baidu"
    version = "baidu_v1"

    def __init__(self, timeout_sec: float = 12.0) -> None:
        self.timeout_sec = timeout_sec

    def fetch_latest_news(self, limit: int = 20) -> list:
        return []

    def fetch_stock_news(self, symbol: str, *, name: str = "", limit: int = 20) -> list:
        code = bare_code(symbol)
        url = "https://finance.pae.baidu.com/selfselect/news"
        try:
            resp = requests.get(
                url,
                params={"finance_type": "stock", "code": code, "market_type": "ab", "rn": int(limit)},
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Referer": "https://gushitong.baidu.com/",
                },
                timeout=self.timeout_sec,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:  # noqa: BLE001
            raise ProviderUnavailable(self.name, str(exc)) from exc
        if str(data.get("ResultCode")) not in {"0", "200", ""}:
            raise ProviderUnavailable(self.name, str(data.get("ResultCode")))
        items: list[dict[str, Any]] = []
        tabs = ((data.get("Result") or {}).get("tabs")) or []
        for tab in tabs:
            contents = tab.get("contents") or []
            if isinstance(contents, list):
                items.extend([c for c in contents if isinstance(c, dict)])
        out = []
        for r in items[:limit]:
            n = row_to_news(
                source=self.name,
                title=str(r.get("title") or ""),
                symbol=symbol,
                name=name,
                url=str(r.get("third_url") or r.get("url") or ""),
                summary=str(r.get("evaluate") or r.get("abstract") or ""),
                published_at=unix_to_iso(r.get("publish_time")),
                media=str(r.get("source") or "百度股市通"),
                source_id=str(r.get("news_id") or ""),
            )
            if n:
                out.append(n)
        return out
