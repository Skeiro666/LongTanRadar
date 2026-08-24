from __future__ import annotations

from ashare.news.schema import PROMPT_VERSION_INTEL

from news_intel_fakes import FakeNewsClient, make_engine, sample_news


def test_model_and_prompt_version_saved(tmp_path):
    n = sample_news("公司预增公告")
    eng = make_engine(tmp_path, FakeNewsClient())
    out = eng.extract_intelligence(n, symbol="000786.SZ", entity_confidence=0.88)
    assert out["model_name"] == "qwen3.5:4b"
    assert out["prompt_version"] == PROMPT_VERSION_INTEL
    assert out["news_id"] == n.id
    assert out["content_hash"]
    assert "input_tokens" in out
    assert "latency_ms" in out
