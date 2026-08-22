from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from ashare.ai.optimizer import apply_proposal, sanitize_proposal


def _optimizer_cfg(cfg: dict[str, Any]) -> dict[str, Any]:
    from ashare.config_loaders import load_yaml_config

    return dict(load_yaml_config(cfg, "optimizer") or cfg.get("optimizer") or {})


def create_experiment(
    cfg: dict[str, Any],
    proposal: dict[str, Any],
    *,
    baseline_config: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
    persist: bool = True,
) -> dict[str, Any]:
    """
    Record optimizer proposal as experiment — does NOT modify production config.
    """
    proposal = sanitize_proposal(dict(proposal or {}))
    oc = _optimizer_cfg(cfg)
    exp = {
        "experiment_id": f"opt_{datetime.now(timezone.utc).strftime('%Y%m%d')}_{uuid4().hex[:8]}",
        "status": "proposed",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "baseline_config": baseline_config or _snapshot_config(cfg),
        "candidate_config": proposal,
        "metrics": (context or {}).get("metrics") or {},
        "train_period": oc.get("train_period"),
        "validation_period": oc.get("validation_period"),
        "test_period": oc.get("test_period"),
        "rationale": proposal.get("rationale") or "",
        "note": "Requires explicit approval before production apply",
    }
    if persist:
        root = Path(cfg.get("_root") or Path(__file__).resolve().parents[2])
        out = root / "data" / "optimizer_experiments.jsonl"
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("a", encoding="utf-8") as f:
            f.write(json.dumps(exp, ensure_ascii=False, default=str) + "\n")
    return exp


def approve_experiment(cfg: dict[str, Any], experiment: dict[str, Any]) -> dict[str, Any]:
    """Apply approved experiment to runtime cfg — explicit human/auto gate only."""
    proposal = dict(experiment.get("candidate_config") or {})
    updated = apply_proposal(cfg, proposal)
    from ashare.ai.optimizer import persist_runtime_overrides

    persist_runtime_overrides(cfg.get("_root") or ".", proposal)
    return {
        "ok": True,
        "experiment_id": experiment.get("experiment_id"),
        "applied": proposal,
        "cfg": updated,
    }


def _snapshot_config(cfg: dict[str, Any]) -> dict[str, Any]:
    keys = ("strategy", "pool", "factors", "ml", "universe")
    return {k: dict(cfg.get(k) or {}) for k in keys if cfg.get(k)}


def list_experiments(cfg: dict[str, Any], *, limit: int = 20) -> list[dict[str, Any]]:
    root = Path(cfg.get("_root") or Path(__file__).resolve().parents[2])
    path = root / "data" / "optimizer_experiments.jsonl"
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except Exception:  # noqa: BLE001
            continue
    return rows[-limit:]
