from __future__ import annotations

from ashare.news.baidu import BaiduFinanceProvider
from ashare.news.eastmoney import EastMoneyProvider
from ashare.news.provider import NewsProvider
from ashare.news.sina import SinaRollProvider
from ashare.news.ths import ThsFlashProvider

_REGISTRY = {
    "eastmoney": EastMoneyProvider,
    "baidu": BaiduFinanceProvider,
    "sina": SinaRollProvider,
    "ths": ThsFlashProvider,
}


def build_providers(names: list[str], *, timeout_sec: float = 12.0) -> list[NewsProvider]:
    out: list[NewsProvider] = []
    for name in names:
        cls = _REGISTRY.get(str(name).strip().lower())
        if cls is None:
            continue
        out.append(cls(timeout_sec=timeout_sec))
    if not out:
        out = [BaiduFinanceProvider(timeout_sec=timeout_sec), EastMoneyProvider(timeout_sec=timeout_sec)]
    return out
