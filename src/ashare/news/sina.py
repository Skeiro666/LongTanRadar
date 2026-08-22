from __future__ import annotations

import logging

import requests

from ashare.news.common import row_to_news, unix_to_iso
from ashare.news.provider import NewsProvider, ProviderUnavailable
from ashare.symbols import bare_code

logger = logging.getLogger("ashare.news.sina")


class SinaRollProvider(NewsProvider):
    """新浪财经滚动资讯：市场/政策；个股用关键词检索同一接口。"""

    name = "sina"
    version = "sina_v1"

    def __init__(self, timeout_sec: float = 12.0) -> None:
        self.timeout_sec = timeout_sec

    def _roll(self, *, keyword: str = "", limit: int = 20) -> list:
        url = "https://feed.mix.sina.com.cn/api/roll/get"
        params = {"pageid": "153", "lid": "2516", "k": keyword, "num": int(limit), "page": 1}
        try:
            resp = requests.get(url, params=params, headers={"User-Agent": "Mozilla/5.0"}, timeout=self.timeout_sec)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:  # noqa: BLE001
            raise ProviderUnavailable(self.name, str(exc)) from exc
        rows = (((data.get("result") or {}).get("data")) or [])[:limit]
        out = []
        for r in rows:
            n = row_to_news(
                source=self.name,
                title=str(r.get("title") or ""),
                url=str(r.get("url") or r.get("URL") or ""),
                summary=str(r.get("intro") or r.get("summary") or ""),
                published_at=unix_to_iso(r.get("ctime") or r.get("intime")),
                media=str(r.get("media_name") or r.get("media") or "新浪财经"),
                source_id=str(r.get("oid") or r.get("docid") or ""),
            )
            if n:
                out.append(n)
        return out

    def fetch_latest_news(self, limit: int = 20) -> list:
        return self._roll(limit=limit)

    def fetch_policy_news(self, *, limit: int = 20) -> list:
        return self._roll(keyword="政策", limit=limit)

    def fetch_stock_news(self, symbol: str, *, name: str = "", limit: int = 20) -> list:
        kw = name or bare_code(symbol)
        items = self._roll(keyword=kw, limit=limit)
        for n in items:
            n.query_symbol = symbol
            n.query_name = name
        return items
