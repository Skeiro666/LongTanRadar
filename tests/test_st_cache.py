"""ST list fetch retry/cache."""

from __future__ import annotations

import json
import time

from ashare.data import akshare_source as src


def test_st_cache_fallback_on_fetch_failure(tmp_path, monkeypatch):
    cache = tmp_path / "data" / "cache" / "st_codes.json"
    cache.parent.mkdir(parents=True)
    cache.write_text(
        json.dumps({"updated_at": time.time(), "codes": ["600000.SH", "000001.SZ"]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(src, "_project_root", lambda: tmp_path)
    monkeypatch.setattr(src, "_ST_MEM", None)

    def _boom():
        raise ConnectionError("Remote end closed connection")

    monkeypatch.setattr(src, "_import_ak", lambda: type("Ak", (), {"stock_zh_a_st_em": staticmethod(_boom)})())
    codes = src.fetch_st_codes(max_retries=1)
    assert codes == {"600000.SH", "000001.SZ"}
