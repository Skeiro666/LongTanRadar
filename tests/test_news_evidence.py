from __future__ import annotations

from ashare.news.engine import NewsIntelligenceEngine
from ashare.news.models import RawNews, make_id, title_hash


def test_collect_stock_marks_evidence_role(monkeypatch, tmp_path):
    good = RawNews(
        id=make_id("N"),
        source="baidu",
        title="汉森制药002412发布半年报预�?,
        fetched_at="2026-08-20T00:00:00+00:00",
        summary="净利润预增",
        published_at="2026-08-20 00:00:00",
        title_hash=title_hash("汉森制药002412发布半年报预�?),
        media="证券时报",
    )

    class FakeP:
        name = "fake"
        version = "fake_v1"

        def fetch_stock_news(self, symbol, *, name="", limit=20):
            return [good]

    monkeypatch.setattr("ashare.news.llm_mapping.news_llm_client", lambda cfg: None)
    eng = NewsIntelligenceEngine({"_root": str(tmp_path), "news": {"fetch": {"min_link_confidence": 0.5}}})
    monkeypatch.setattr(eng, "providers", [FakeP()])
    pkg = eng.collect_stock("002412.SZ", name="汉森制药", persist=False)
    assert pkg["news_role"] == "evidence"
    titles = [x.get("title") for x in pkg.get("last_7d") or []]
    assert any("汉森制药" in t for t in titles)
