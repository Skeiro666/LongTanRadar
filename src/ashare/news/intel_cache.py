from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def content_hash(title: str, summary: str, content: str) -> str:
    blob = f"{title or ''}\n{summary or ''}\n{(content or '')[:4000]}"
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


class NewsIntelCache:
    """Append-only cache: news_id + content_hash + model + prompt_version."""

    def __init__(self, root: Path | str, *, filename: str = "news_intel_cache.jsonl") -> None:
        self.path = Path(root) / "data" / "news" / filename
        self._lock = threading.Lock()
        self._mem: dict[str, dict[str, Any]] = {}
        self._loaded = False

    def _key(self, news_id: str, chash: str, model: str, prompt_version: str) -> str:
        return f"{news_id}|{chash}|{model}|{prompt_version}"

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if not self.path.exists():
            return
        try:
            with self.path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    k = self._key(
                        str(row.get("news_id") or ""),
                        str(row.get("content_hash") or ""),
                        str(row.get("model") or ""),
                        str(row.get("prompt_version") or ""),
                    )
                    self._mem[k] = row
        except OSError:
            return

    def get(
        self,
        *,
        news_id: str,
        content_hash: str,
        model: str,
        prompt_version: str,
    ) -> dict[str, Any] | None:
        with self._lock:
            self._load()
            return self._mem.get(self._key(news_id, content_hash, model, prompt_version))

    def put(self, row: dict[str, Any]) -> None:
        rec = dict(row)
        rec.setdefault("created_at", datetime.now(timezone.utc).isoformat())
        rec.setdefault("status", "ok")
        k = self._key(
            str(rec.get("news_id") or ""),
            str(rec.get("content_hash") or ""),
            str(rec.get("model") or ""),
            str(rec.get("prompt_version") or ""),
        )
        with self._lock:
            self._load()
            self._mem[k] = rec
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")


content_hash = content_hash
NewsIntelCache = NewsIntelCache
