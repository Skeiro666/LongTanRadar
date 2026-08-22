from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

PIPELINE_GUIDE: list[dict[str, str]] = [
    {"phase": "pool", "label": "龙头/事件池", "typical": "5–15s", "note": "涨停/强势/利润断层 akshare"},
    {"phase": "panel", "label": "日线缓存", "typical": "0–3min", "note": "缺缓存时逐只下载"},
    {"phase": "news_discovery", "label": "新闻发现", "typical": "10–30s", "note": "百度/东财/新浪"},
    {"phase": "candidate", "label": "候选 Union + 逐股新闻", "typical": "1–5min", "note": "最多 20 只 × 3 源"},
    {"phase": "roundtable", "label": "圆桌 Benchmark", "typical": "2–8min", "note": "~5 次 LLM（不控交易）"},
    {"phase": "council", "label": "Council 研究", "typical": "5–15min", "note": "最多 12 只串行 × 多角色 LLM"},
    {"phase": "decision", "label": "Canonical 决策", "typical": "<5s", "note": "风控 + 权重"},
    {"phase": "outcome", "label": "归因 / CSI300", "typical": "5–20s", "note": "benchmark + 写 outcomes"},
    {"phase": "persist", "label": "持久化", "typical": "<5s", "note": "研报 JSON / Redis / PG"},
]


class ResearchProgressTracker:
    """In-memory research run log for UI polling (single-flight)."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.reset()

    def reset(self) -> None:
        with self._lock:
            self.status = "idle"
            self.run_id: str | None = None
            self.started_at: str | None = None
            self.finished_at: str | None = None
            self.steps: list[dict[str, Any]] = []
            self.result: dict[str, Any] | None = None
            self.error: str | None = None
            self._open_phase: str | None = None

    @property
    def running(self) -> bool:
        with self._lock:
            return self.status == "running"

    def begin(self) -> str:
        with self._lock:
            if self.status == "running":
                raise RuntimeError("research already running")
            self.reset()
            self.status = "running"
            self.run_id = f"run_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:6]}"
            self.started_at = datetime.now(timezone.utc).isoformat()
            return self.run_id

    def log(self, phase: str, message: str, *, level: str = "info", detail: Any = None) -> None:
        with self._lock:
            self.steps.append(
                {
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "phase": phase,
                    "level": level,
                    "message": message,
                    "detail": detail,
                    "type": "log",
                }
            )

    @contextmanager
    def step(self, phase: str, label: str, *, note: str = ""):
        t0 = time.time()
        entry: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "phase": phase,
            "label": label,
            "note": note,
            "status": "running",
            "type": "step",
        }
        with self._lock:
            self._open_phase = phase
            self.steps.append(entry)
        try:
            yield entry
            entry["status"] = "done"
        except Exception as exc:
            entry["status"] = "error"
            entry["error"] = str(exc)[:500]
            self.log(phase, f"失败: {exc}", level="error")
            raise
        finally:
            entry["duration_sec"] = round(time.time() - t0, 2)
            entry["finished_at"] = datetime.now(timezone.utc).isoformat()
            with self._lock:
                self._open_phase = None

    def finish(self, result: dict[str, Any]) -> None:
        with self._lock:
            self.status = "done"
            self.finished_at = datetime.now(timezone.utc).isoformat()
            self.result = result

    def fail(self, error: str) -> None:
        with self._lock:
            self.status = "error"
            self.finished_at = datetime.now(timezone.utc).isoformat()
            self.error = error[:800]

    def timing_table(self) -> list[dict[str, Any]]:
        with self._lock:
            steps = [s for s in self.steps if s.get("type") == "step"]
        by_phase = {s["phase"]: s for s in steps}
        rows: list[dict[str, Any]] = []
        for g in PIPELINE_GUIDE:
            act = by_phase.get(g["phase"])
            rows.append(
                {
                    **g,
                    "status": (act or {}).get("status") or "pending",
                    "duration_sec": (act or {}).get("duration_sec"),
                    "error": (act or {}).get("error"),
                }
            )
        return rows

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            elapsed = None
            if self.started_at:
                t0 = datetime.fromisoformat(self.started_at.replace("Z", "+00:00"))
                t1 = (
                    datetime.fromisoformat(self.finished_at.replace("Z", "+00:00"))
                    if self.finished_at
                    else datetime.now(timezone.utc)
                )
                elapsed = round((t1 - t0).total_seconds(), 1)
            return {
                "status": self.status,
                "run_id": self.run_id,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
                "elapsed_sec": elapsed,
                "current_phase": self._open_phase,
                "steps": list(self.steps[-200:]),
                "pipeline_timing": self.timing_table(),
                "pipeline_guide": PIPELINE_GUIDE,
                "error": self.error,
                "has_result": self.result is not None,
            }

    def run_log(self) -> dict[str, Any]:
        snap = self.snapshot()
        return {
            "run_id": snap["run_id"],
            "elapsed_sec": snap["elapsed_sec"],
            "pipeline_timing": snap["pipeline_timing"],
            "steps": snap["steps"],
        }


_tracker = ResearchProgressTracker()


def get_research_progress() -> ResearchProgressTracker:
    return _tracker
