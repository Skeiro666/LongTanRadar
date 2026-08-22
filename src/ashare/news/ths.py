from __future__ import annotations

import logging

import requests

from ashare.news.common import row_to_news, unix_to_iso
from ashare.news.provider import NewsProvider, ProviderUnavailable


class ThsFlashProvider(NewsProvider):
    """同花顺 7x24 快讯（全市场）。个股接口不稳定时仍可作为宏观/政策补充。"""

    name = "ths"
    version = "ths_v1"

    def __init__(self, timeout_sec: float = 12.0) -> None:
        self.timeout_sec = timeout_sec

    def fetch_stock_news(self, symbol: str, *, name: str = "", limit: int = 20) -> list:
        # 该接口对 code 过滤不稳定，不当作个股新闻，避免错误关联。
        return []

    def fetch_latest_news(self, limit: int = 20) -> list:
        url = "https://news.10jqka.com.cn/tapp/news/push/stock/"
        try:
            resp = requests.get(
                url,
                params={"page": 1, "pagesize": int(limit), "track": "website"},
                headers={"User-Agent": "Mozilla/5.0", "Referer": "https://news.10jqka.com.cn/"},
                timeout=self.timeout_sec,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:  # noqa: BLE001
            raise ProviderUnavailable(self.name, str(exc)) from exc
        if str(data.get("code")) not in {"200", "0"}:
            raise ProviderUnavailable(self.name, str(data.get("msg") or data.get("code")))
        rows = (((data.get("data") or {}).get("list")) or [])[:limit]
        out = []
        for r in rows:
            n = row_to_news(
                source=self.name,
                title=str(r.get("title") or ""),
                url=str(r.get("url") or r.get("shareUrl") or ""),
                summary=str(r.get("digest") or ""),
                published_at=unix_to_iso(r.get("ctime") or r.get("rtime") or r.get("time")),
                media=str(r.get("source") or "同花顺"),
                source_id=str(r.get("seq") or r.get("id") or ""),
            )
            if n:
                out.append(n)
        return out
