from __future__ import annotations

from ashare.news.models import RawNews

_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("FINANCIAL", ("业绩", "预增", "预减", "年报", "季报", "净利润", "营收", "扭亏")),
    ("ORDER", ("订单", "合同", "中标", "重大合同")),
    ("PRICE", ("涨价", "提价", "降价", "价格上调")),
    ("CAPACITY", ("产能", "投产", "扩产")),
    ("M_AND_A", ("并购", "收购", "重组", "资产注入")),
    ("SHARE_BUYBACK", ("回购",)),
    ("INSIDER_SELL", ("减持",)),
    ("INSIDER_BUY", ("增持",)),
    ("REGULATORY", ("立案", "处罚", "监管", "问询")),
    ("LITIGATION", ("诉讼", "仲裁")),
    ("POLICY", ("政策", "补贴", "规划", "国务院", "发改委")),
    ("PRODUCT", ("新品", "发布", "产品")),
    ("MANAGEMENT", ("董事长", "总经理", "辞职", "任命")),
    ("DIVIDEND", ("分红", "派息")),
    ("MARKET", ("涨停", "跌停", "龙虎榜")),
]


def classify_news(news: RawNews) -> str:
    text = f"{news.title}{news.summary}"
    for cat, keys in _RULES:
        if any(k in text for k in keys):
            return cat
    if any(k in (news.media or "") for k in ("公告", "交易所")):
        return "COMPANY"
    return "OTHER"
