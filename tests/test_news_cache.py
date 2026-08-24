from __future__ import annotations

from news_intel_fakes import FakeNewsClient, make_engine, sample_news


def test_same_news_hits_cache(tmp_path):
    n = sample_news("北新建材签订重大合同订单")
    client = FakeNewsClient()
    eng = make_engine(tmp_path, client)
    a = eng.extract_intelligence(n, symbol="000786.SZ", entity_confidence=0.9)
    b = eng.extract_intelligence(n, symbol="000786.SZ", entity_confidence=0.9)
    assert a["status"] == "ok"
    assert b["cache_hit"] is True
    assert client.calls == 1
    assert b["model_name"] == "qwen3.5:latest"
    assert b["prompt_version"]
