from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib

logger = logging.getLogger("ashare.ml.registry")


def models_dir(cfg: dict[str, Any]) -> Path:
    ml = cfg.get("ml", {})
    root = Path(cfg.get("_root", "."))
    d = Path(ml.get("models_dir", "data/models"))
    if not d.is_absolute():
        d = root / d
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_run(
    cfg: dict[str, Any],
    model: Any,
    meta: dict[str, Any],
    run_id: str | None = None,
) -> dict[str, Any]:
    mid = run_id or datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    folder = models_dir(cfg) / mid
    folder.mkdir(parents=True, exist_ok=True)
    model_path = folder / "model.joblib"
    meta_path = folder / "meta.json"
    joblib.dump(model, model_path)
    payload = {**meta, "run_id": mid, "model_path": str(model_path)}
    meta_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    # pointer to latest
    latest = models_dir(cfg) / "latest.json"
    latest.write_text(json.dumps({"run_id": mid, "model_path": str(model_path)}, indent=2), encoding="utf-8")
    logger.info("Saved model run %s", mid)
    return payload


def list_models(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    root = models_dir(cfg)
    out: list[dict[str, Any]] = []
    for child in sorted(root.iterdir(), reverse=True):
        if not child.is_dir():
            continue
        meta_path = child / "meta.json"
        if not meta_path.exists():
            continue
        try:
            out.append(json.loads(meta_path.read_text(encoding="utf-8")))
        except Exception:  # noqa: BLE001
            continue
    return out


def resolve_model_path(cfg: dict[str, Any], run_id: str | None = None) -> Path | None:
    ml = cfg.get("ml", {})
    explicit = ml.get("model_path")
    if explicit and not run_id:
        p = Path(explicit)
        if not p.is_absolute():
            p = Path(cfg["_root"]) / p
        if p.exists():
            return p
    if run_id:
        p = models_dir(cfg) / run_id / "model.joblib"
        return p if p.exists() else None
    latest = models_dir(cfg) / "latest.json"
    if latest.exists():
        data = json.loads(latest.read_text(encoding="utf-8"))
        p = Path(data.get("model_path", ""))
        if p.exists():
            return p
    models = list_models(cfg)
    if models:
        p = Path(models[0].get("model_path", ""))
        return p if p.exists() else None
    return None


def load_model(cfg: dict[str, Any], run_id: str | None = None) -> Any | None:
    path = resolve_model_path(cfg, run_id=run_id)
    if path is None:
        return None
    return joblib.load(path)
