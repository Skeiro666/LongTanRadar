from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ashare.config_loaders import load_yaml_config
from ashare.leader.lifecycle import (
    BUY_CANDIDATE,
    BUY_READY,
    DROPPED,
    FOCUS,
    LEADER_CANDIDATE,
    LEADER_CONFIRMED,
    NEW_LIMIT_UP,
    WAIT,
)
from ashare.symbols import to_symbol


def _focus_cfg(cfg: dict[str, Any] | None) -> dict[str, Any]:
    base = dict(load_yaml_config(cfg, "leader").get("focus") or {})
    defaults = {
        "max_focus_stocks": 8,
        "state_file": "data/leader/focus_watchlist.json",
        "persist_across_cycles": True,
        "min_leader_score": 0.35,
    }
    return {**defaults, **base}


class FocusWatchlistStore:
    """Persistent focus watchlist — survives ranking cutoffs between cycles."""

    def __init__(self, cfg: dict[str, Any] | None = None) -> None:
        self.cfg = cfg or {}
        self.fc = _focus_cfg(self.cfg)
        root = Path(self.cfg.get("_root") or Path(__file__).resolve().parents[3])
        sf = Path(str(self.fc["state_file"]))
        if not sf.is_absolute():
            sf = root / sf
        self.path = sf
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> dict[str, dict[str, Any]]:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if "items" in data:
                items = data.get("items") or []
                if isinstance(items, list):
                    return {to_symbol(x["symbol"]): x for x in items if x.get("symbol")}
                return {}
            if isinstance(data, dict) and all(isinstance(v, dict) for v in data.values()):
                return {to_symbol(k): v for k, v in data.items()}
        except Exception:
            return {}
        return {}

    def save(self, items: dict[str, dict[str, Any]]) -> None:
        payload = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "items": list(items.values()),
        }
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    def merge_cycle(
        self,
        candidates: list[dict[str, Any]],
        *,
        as_of: str,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Update focus state, merge persisted symbols back into candidate list."""
        existing = self.load()
        by_sym = {to_symbol(c["symbol"]): dict(c) for c in candidates if c.get("symbol")}
        max_n = int(self.fc["max_focus_stocks"])
        stats = {"promoted": 0, "dropped": 0, "retained": 0, "merged_from_focus": 0}

        for sym, row in list(existing.items()):
            if sym in by_sym:
                prev_lc = str(existing[sym].get("lifecycle") or "")
                cur = by_sym[sym]
                cur["focus_cycles"] = int(existing[sym].get("focus_cycles") or 0) + 1
                cur["lifecycle_prev"] = prev_lc
                if self._should_drop(cur):
                    cur["lifecycle"] = DROPPED
                    cur["drop_reason"] = cur.get("drop_reason") or "drop_rules"
                    stats["dropped"] += 1
                    existing.pop(sym, None)
                    continue
                lc = str(cur.get("lifecycle") or prev_lc or LEADER_CANDIDATE)
                cur["lifecycle"] = self._promote(lc, cur)
                cur["in_focus_watchlist"] = lc in {FOCUS, BUY_CANDIDATE, BUY_READY} or cur["lifecycle"] in {
                    FOCUS,
                    BUY_CANDIDATE,
                    BUY_READY,
                }
                existing[sym] = self._snapshot(cur, as_of)
                stats["retained"] += 1
            elif self._retain_off_rank(existing[sym]):
                off = dict(existing[sym])
                off["merged_from_focus"] = True
                off["lifecycle"] = str(off.get("lifecycle") or FOCUS)
                off["in_focus_watchlist"] = True
                off["off_rank_retained"] = True
                by_sym[sym] = {**off, **self._minimal_rehydrate(off)}
                existing[sym] = self._snapshot(by_sym[sym], as_of)
                stats["merged_from_focus"] += 1
                stats["retained"] += 1
            else:
                existing.pop(sym, None)
                stats["dropped"] += 1

        for sym, row in by_sym.items():
            if sym in existing:
                continue
            if str(row.get("lifecycle") or "").upper() == DROPPED:
                continue
            lc = self._initial_lifecycle(row)
            row["lifecycle"] = lc
            if lc in {FOCUS, BUY_CANDIDATE, BUY_READY, LEADER_CONFIRMED}:
                existing[sym] = self._snapshot(row, as_of)
                stats["promoted"] += 1

        focus_syms = sorted(
            existing.keys(),
            key=lambda s: float(existing[s].get("leader_score") or 0),
            reverse=True,
        )[:max_n]
        trimmed = {s: existing[s] for s in focus_syms}
        if len(existing) > max_n:
            stats["dropped"] += len(existing) - max_n
        self.save(trimmed)

        merged = list(by_sym.values())
        for sym, snap in trimmed.items():
            if sym not in by_sym:
                merged.append(dict(snap))
        merged.sort(key=lambda x: float(x.get("leader_score") or 0), reverse=True)
        return merged, stats

    def _snapshot(self, row: dict[str, Any], as_of: str) -> dict[str, Any]:
        return {
            "symbol": to_symbol(row["symbol"]),
            "name": row.get("name"),
            "as_of": as_of,
            "lifecycle": row.get("lifecycle"),
            "leader_score": row.get("leader_score"),
            "trade_timing_score": row.get("trade_timing_score"),
            "trade_timing_action": row.get("trade_timing_action"),
            "stage": row.get("stage"),
            "chase_score": row.get("chase_score"),
            "chase_level": row.get("chase_level"),
            "board_count": row.get("board_count"),
            "news_score": row.get("news_score"),
            "state_version": row.get("state_version"),
            "focus_cycles": row.get("focus_cycles", 0),
            "drop_reason": row.get("drop_reason"),
            "status_reason": row.get("status_reason"),
            "next_refresh": row.get("next_refresh"),
        }

    def _minimal_rehydrate(self, snap: dict[str, Any]) -> dict[str, Any]:
        return {
            "symbol": snap["symbol"],
            "name": snap.get("name"),
            "leader_score": snap.get("leader_score"),
            "stage": snap.get("stage"),
            "chase_score": snap.get("chase_score"),
            "trade_timing_score": snap.get("trade_timing_score"),
            "trade_timing_action": snap.get("trade_timing_action"),
            "board_count": snap.get("board_count"),
            "candidate_sources": snap.get("candidate_sources") or ["event"],
            "candidate_score": snap.get("leader_score"),
            "in_council": True,
            "council_tier": "full",
        }

    def _initial_lifecycle(self, row: dict[str, Any]) -> str:
        ls = float(row.get("leader_score") or 0)
        ta = str(row.get("trade_timing_action") or WAIT).upper()
        st = str(row.get("stage") or "EARLY").upper()
        board = int(row.get("board_count") or 0)
        min_ls = float(self.fc["min_leader_score"])
        if ta == BUY_READY:
            return BUY_READY
        if ta == BUY_CANDIDATE:
            return BUY_CANDIDATE
        if ls >= min_ls and board >= 2:
            return LEADER_CONFIRMED
        if board >= 1 or ls >= 0.25:
            return LEADER_CANDIDATE
        return NEW_LIMIT_UP

    def _promote(self, lc: str, row: dict[str, Any]) -> str:
        if str(row.get("lifecycle") or "").upper() == DROPPED:
            return DROPPED
        ta = str(row.get("trade_timing_action") or "").upper()
        ls = float(row.get("leader_score") or 0)
        st = str(row.get("stage") or "").upper()
        if st == "BREAKDOWN":
            return DROPPED
        if ta == BUY_READY:
            return BUY_READY
        if ta == BUY_CANDIDATE:
            return BUY_CANDIDATE
        if ls >= float(self.fc["min_leader_score"]) and lc in {LEADER_CANDIDATE, LEADER_CONFIRMED, FOCUS, WAIT}:
            return FOCUS
        if lc == NEW_LIMIT_UP:
            return LEADER_CANDIDATE
        return lc

    def _should_drop(self, row: dict[str, Any]) -> bool:
        lc = dict(load_yaml_config(self.cfg, "leader").get("lifecycle") or {})
        st = str(row.get("stage") or "").upper()
        if lc.get("drop_on_breakdown") and st == "BREAKDOWN":
            row["drop_reason"] = "stage_breakdown"
            return True
        neg = float(row.get("negative_evidence_score") or 0)
        if neg >= 0.85:
            row["drop_reason"] = "severe_negative_news"
            return True
        stale = int(lc.get("drop_stale_cycles") or 5)
        if str(row.get("lifecycle")) == DROPPED:
            return True
        if int(row.get("focus_cycles") or 0) >= stale and float(row.get("trade_timing_score") or 0) < 0.2:
            row["drop_reason"] = "stale_no_improvement"
            return True
        return False

    def _retain_off_rank(self, snap: dict[str, Any]) -> bool:
        lc = str(snap.get("lifecycle") or "")
        return lc in {FOCUS, BUY_CANDIDATE, BUY_READY}
