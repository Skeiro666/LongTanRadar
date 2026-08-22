from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("ashare.account.ledger")


class Ledger:
    """Persist paper account state and trade history to JSON."""

    def __init__(self, state_file: str | Path) -> None:
        self.state_file = Path(state_file)
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.trades: list[dict[str, Any]] = []
        self.state: dict[str, Any] = {}

    def load(self) -> Optional[dict[str, Any]]:
        if not self.state_file.exists():
            return None
        data = json.loads(self.state_file.read_text(encoding="utf-8"))
        self.state = data.get("state", {})
        self.trades = data.get("trades", [])
        logger.info("Loaded ledger from %s (%d trades)", self.state_file, len(self.trades))
        return self.state

    def save(self, state: dict[str, Any]) -> None:
        self.state = state
        payload = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "state": state,
            "trades": self.trades,
        }
        self.state_file.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    def append_trade(self, trade: dict[str, Any]) -> None:
        self.trades.append(trade)
        if self.state:
            self.save(self.state)
