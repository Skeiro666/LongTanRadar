from __future__ import annotations

import re

from ashare.news.models import NewsEntity, RawNews
from ashare.symbols import bare_code, to_symbol

_CODE6 = re.compile(r"(?<!\d)(\d{6})(?!\d)")
_DOT_SYM = re.compile(r"(?<!\d)(\d{6})\.(SH|SZ|BJ|SS)", re.I)


def codes_in_text(text: str) -> list[str]:
    """Rule extract A-share codes from free text. Dates like 20260821 are skipped."""
    blob = text or ""
    found: list[str] = []
    seen: set[str] = set()
    for m in _DOT_SYM.finditer(blob):
        sym = to_symbol(f"{m.group(1)}.{m.group(2)}")
        if sym not in seen:
            seen.add(sym)
            found.append(sym)
    for m in _CODE6.finditer(blob):
        raw = m.group(1)
        if raw.startswith("20"):
            continue
        try:
            sym = to_symbol(raw)
        except Exception:  # noqa: BLE001
            continue
        if sym not in seen:
            seen.add(sym)
            found.append(sym)
    return found


_SKIP_NAMES = {"集团", "股份", "科技", "有限公司", "银行", "公司", "中国", "上海", "深圳"}
LLM_INFERENCE_MAX_CONF = 0.45


def _blob(news: RawNews) -> str:
    return f"{news.title}\n{news.summary}\n{news.content}"


def link_entities_open(
    news: RawNews,
    *,
    name_map: dict[str, str] | None = None,
    aliases: dict[str, str] | None = None,
) -> list[NewsEntity]:
    """
    News → Stock without a pre-chosen query symbol.
    Priority: code > official name > alias. Never uses query_weak.
    LLM inference is a separate helper with capped confidence.
    """
    blob = _blob(news)
    hits: list[tuple[int, int, str, str, str, float]] = []  # start,end,sym,name,method,conf

    for m in _DOT_SYM.finditer(blob):
        sym = to_symbol(f"{m.group(1)}.{m.group(2)}")
        hits.append((m.start(), m.end(), sym, "", "code", 0.82))
    for m in _CODE6.finditer(blob):
        raw = m.group(1)
        if raw.startswith("20"):
            continue
        sym = to_symbol(raw)
        hits.append((m.start(), m.end(), sym, "", "code", 0.82))

    phrases: list[tuple[str, str, str, float]] = []
    for sym, nm in (name_map or {}).items():
        nm = str(nm or "").strip()
        if len(nm) < 3 or nm in _SKIP_NAMES:
            continue
        phrases.append((nm, to_symbol(sym), "official_name", 0.88))
    for alias, sym in (aliases or {}).items():
        al = str(alias or "").strip()
        if len(al) < 2 or al in _SKIP_NAMES:
            continue
        phrases.append((al, to_symbol(sym), "alias", 0.80))
    phrases.sort(key=lambda x: len(x[0]), reverse=True)

    for phrase, sym, method, conf in phrases:
        start = 0
        while True:
            i = blob.find(phrase, start)
            if i < 0:
                break
            hits.append((i, i + len(phrase), sym, phrase, method, conf))
            start = i + len(phrase)

    hits.sort(key=lambda h: (h[0], -(h[1] - h[0])))
    picked: list[tuple[int, int, str, str, str, float]] = []
    last_end = -1
    for h in hits:
        if h[0] < last_end:
            continue
        picked.append(h)
        last_end = h[1]

    by_sym: dict[str, tuple[str, str, float, str]] = {}
    for _s, _e, sym, nm, method, conf in picked:
        prev = by_sym.get(sym)
        if prev is None or conf > prev[2]:
            by_sym[sym] = (nm, method, conf, method)
        elif method == "code" and prev[1] == "official_name":
            by_sym[sym] = (prev[0], "title+code", 0.97, "title+code")
        elif method == "official_name" and prev[1] == "code":
            by_sym[sym] = (nm, "title+code", 0.97, "title+code")

    out: list[NewsEntity] = []
    for sym, (nm, src, conf, method) in by_sym.items():
        out.append(
            NewsEntity(
                news_id=news.id,
                entity_type="stock",
                symbol=sym,
                name=nm,
                confidence=conf,
                link_source=src,
                mapping_method=method,
            )
        )
    out.sort(key=lambda e: -e.confidence)
    return out


def llm_inference_entities(
    news: RawNews,
    guesses: list[dict[str, str]],
) -> list[NewsEntity]:
    """LLM-proposed beneficiaries. Confidence is hard-capped below rule matches."""
    out: list[NewsEntity] = []
    for g in guesses:
        sym = str(g.get("symbol") or "").strip()
        if not sym:
            continue
        out.append(
            NewsEntity(
                news_id=news.id,
                entity_type="stock",
                symbol=to_symbol(sym),
                name=str(g.get("name") or ""),
                confidence=min(LLM_INFERENCE_MAX_CONF, float(g.get("confidence") or LLM_INFERENCE_MAX_CONF)),
                link_source="llm_inference",
                mapping_method="llm_inference",
            )
        )
    return out


def link_entities(news: RawNews, *, symbol: str, name: str = "") -> list[NewsEntity]:
    """
    Do not assume search hits belong to the queried stock.
    Confidence from title/content mention of name or 6-digit code.
    """
    sym = to_symbol(symbol)
    code = bare_code(sym)
    blob = f"{news.title}\n{news.summary}\n{news.content}"
    name_hit = bool(name) and name in blob
    code_hit = bool(re.search(rf"(?<!\d){re.escape(code)}(?!\d)", blob))
    if name_hit and code_hit:
        conf, src = 0.97, "title+code"
    elif name_hit:
        conf, src = 0.88, "title"
    elif code_hit:
        conf, src = 0.82, "code"
    else:
        conf, src = 0.35, "query_weak"
    return [
        NewsEntity(
            news_id=news.id,
            entity_type="stock",
            symbol=sym,
            name=name or "",
            confidence=conf,
            link_source=src,
            mapping_method=src,
        )
    ]
