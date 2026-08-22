from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ashare.news.models import make_id


class EvidenceRegistry:
    """Assign stable evidence IDs (E1001…) for AI citation without repeating news bodies."""

    def __init__(self, cfg: dict[str, Any] | None = None) -> None:
        self.cfg = cfg or {}
        root = Path(self.cfg.get("_root") or Path(__file__).resolve().parents[2])
        self.path = root / "data" / "news" / "evidence_registry.jsonl"
        self._seq = 1000
        self._by_key: dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            for line in self.path.read_text(encoding="utf-8").splitlines():
                row = json.loads(line)
                eid = str(row.get("evidence_id") or "")
                key = str(row.get("key") or "")
                if eid.startswith("E") and key:
                    self._by_key[key] = eid
                    try:
                        self._seq = max(self._seq, int(eid[1:]))
                    except ValueError:
                        pass
        except Exception:  # noqa: BLE001
            pass

    def _next_id(self) -> str:
        self._seq += 1
        return f"E{self._seq}"

    def register(
        self,
        *,
        key: str,
        title: str,
        source: str = "",
        url: str = "",
        published_at: str = "",
        news_id: str = "",
        symbol: str = "",
        persist: bool = True,
    ) -> str:
        if key in self._by_key:
            return self._by_key[key]
        eid = self._next_id()
        self._by_key[key] = eid
        row = {
            "evidence_id": eid,
            "key": key,
            "title": title[:300],
            "source": source,
            "url": url,
            "published_at": published_at,
            "news_id": news_id,
            "symbol": symbol,
        }
        if persist:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
            except Exception:  # noqa: BLE001
                pass
        return eid

    @staticmethod
    def evidence_key(news_id: str, title: str) -> str:
        from ashare.news.models import title_hash

        return f"{news_id}:{title_hash(title)[:16]}"
