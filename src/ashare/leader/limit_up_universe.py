from __future__ import annotations

from typing import Any

from ashare.config_loaders import load_yaml_config
from ashare.symbols import to_symbol


def _leader_cfg(cfg: dict[str, Any] | None) -> dict[str, Any]:
    return load_yaml_config(cfg, "leader")


def is_limit_up_row(row: dict[str, Any], feats: dict[str, Any] | None = None) -> bool:
    sources = set(str(s) for s in (row.get("sources") or []))
    if row.get("source") == "limit_up":
        sources.add("limit_up")
    if "limit_up" in sources:
        return True
    if int(row.get("board_count") or 0) >= 1 and float(row.get("pct_chg") or 0) >= 9.5:
        return True
    if feats and feats.get("limit_up_today"):
        return True
    return bool(row.get("limit_up_today"))


class LimitUpUniverse:
    """Hard gate: only limit-up names enter leader research pool."""

    def __init__(self, cfg: dict[str, Any] | None = None) -> None:
        self.cfg = cfg or {}
        self.lc = _leader_cfg(self.cfg)
        self.uc = dict(self.lc.get("universe") or {})

    def filter_rows(
        self,
        rows: list[dict[str, Any]],
        *,
        feats_by_sym: dict[str, dict[str, Any]] | None = None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        if not bool(self.lc.get("enabled", True)):
            return rows, []
        if not bool(self.uc.get("require_limit_up", True)):
            return rows, []
        feats_by_sym = feats_by_sym or {}
        passed: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        for r in rows:
            sym = to_symbol(r.get("symbol") or "")
            if not sym:
                continue
            feats = feats_by_sym.get(sym) or {}
            if is_limit_up_row(r, feats):
                passed.append(r)
            else:
                rejected.append(
                    {
                        "symbol": sym,
                        "reject_reason": "NOT_LIMIT_UP",
                        "name": r.get("name"),
                        "sources": r.get("sources"),
                    }
                )
        passed.sort(
            key=lambda x: (
                float((feats_by_sym.get(to_symbol(x["symbol"])) or {}).get("consecutive_limit_up") or 0),
                int(x.get("board_count") or 0),
                float(x.get("event_score") or 0),
            ),
            reverse=True,
        )
        return passed, rejected

    def reject_news_only(self, row: dict[str, Any], feats: dict[str, Any] | None = None) -> bool:
        if not bool(self.uc.get("reject_news_only_without_limit_up", True)):
            return False
        srcs = set(row.get("candidate_sources") or row.get("sources") or [])
        if srcs == {"news"} and not is_limit_up_row(row, feats):
            return True
        return False
