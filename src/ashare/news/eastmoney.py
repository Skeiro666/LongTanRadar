from __future__ import annotations

import json
import logging
import re
from typing import Any

import requests

from ashare.news.models import RawNews, make_id, title_hash, utc_now
from ashare.news.provider import NewsProvider, ProviderUnavailable
from ashare.symbols import bare_code, to_symbol

logger = logging.getLogger("ashare.news.eastmoney")


def _strip_em(text: str) -> str:
    return re.sub(r"</?em>", "", text or "").strip()


class EastMoneyProvider(NewsProvider):
    name = "eastmoney"
    version = "eastmoney_v1"

    def __init__(self, timeout_sec: float = 12.0) -> None:
        self.timeout_sec = timeout_sec

    def fetch_latest_news(self, limit: int = 20) -> list[RawNews]:
        # Same search API without a stock code is too noisy; leave empty rather than fabricate.
        return []

    def fetch_announcement(self, symbol: str, *, limit: int = 20) -> list[RawNews]:
        return []

    def fetch_policy_news(self, *, limit: int = 20) -> list[RawNews]:
        return []

    def fetch_stock_news(self, symbol: str, *, name: str = "", limit: int = 20) -> list[RawNews]:
        code = bare_code(symbol)
        # Prefer company name — code-only search returns unrelated market articles.
        keyword = (name or "").strip() or code
        try:
            rows = self._search(keyword, limit=limit)
        except Exception as exc:  # noqa: BLE001
            logger.warning("EastMoneyProvider unavailable: %s", exc)
            raise ProviderUnavailable(self.name, str(exc)) from exc
        out: list[RawNews] = []
        now = utc_now().isoformat()
        for r in rows:
            title = _strip_em(str(r.get("title") or ""))
            if not title:
                continue
            code = str(r.get("code") or r.get("id") or r.get("uniqueId") or "")
            url = str(r.get("url") or r.get("Url") or r.get("jumpUrl") or "")
            if not url and code:
                url = f"http://finance.eastmoney.com/a/{code}.html"
            content = _strip_em(str(r.get("content") or r.get("contentText") or ""))
            news = RawNews(
                id=make_id("N"),
                source=self.name,
                source_id=code,
                url=url,
                title=title,
                content=content,
                summary=content[:400],
                published_at=str(r.get("date") or r.get("showTime") or ""),
                fetched_at=now,
                author=str(r.get("author") or ""),
                media=str(r.get("mediaName") or r.get("media") or ""),
                title_hash=title_hash(title),
                query_symbol=to_symbol(symbol),
                query_name=name or "",
                raw_payload={"keys": list(r.keys())[:40]},
            )
            out.append(news)
        return out

    def _search(self, keyword: str, limit: int) -> list[dict[str, Any]]:
        param = (
            '{"uid":"","keyword":"%s","type":["cmsArticleWebOld"],"client":"web",'
            '"clientType":"web","clientVersion":"curr",'
            '"param":{"cmsArticleWebOld":{"searchScope":"default","sort":"default",'
            '"pageIndex":1,"pageSize":%d}}}'
        ) % (keyword, int(limit))
        url = "http://search-api-web.eastmoney.com/search/jsonp?cb=jQuery&param=" + requests.utils.quote(
            param, safe=""
        )
        resp = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0", "Referer": "https://so.eastmoney.com/"},
            timeout=self.timeout_sec,
        )
        resp.raise_for_status()
        text = resp.text
        m = re.search(r"^[^(]+\((\{.*\})\)\s*$", text, re.DOTALL)
        if not m:
            raise ProviderUnavailable(self.name, "jsonp parse failed")
        data = json.loads(m.group(1))
        return list((((data.get("result") or {}).get("cmsArticleWebOld")) or [])[:limit])
