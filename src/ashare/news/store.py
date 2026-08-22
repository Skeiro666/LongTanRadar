from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ashare.news.models import RawNews


class NewsStore:
    """File cache shared across symbols. Independent of LLM."""

    def __init__(self, root: Path) -> None:
        self.dir = Path(root) / "data" / "news"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path = self.dir / "raw_news.jsonl"

    def append(self, items: list[RawNews]) -> None:
        if not items:
            return
        with self.path.open("a", encoding="utf-8") as f:
            for n in items:
                f.write(json.dumps(n.to_dict(), ensure_ascii=False, default=str) + "\n")

    def load_all(self, limit: int = 5000) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        rows = []
        for line in self.path.read_text(encoding="utf-8").splitlines()[-limit:]:
            try:
                rows.append(json.loads(line))
            except Exception:  # noqa: BLE001
                continue
        return rows
