from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def _root_from_cfg(cfg: dict[str, Any] | None) -> Path:
    if cfg and cfg.get("_root"):
        return Path(cfg["_root"])
    # src/ashare/config_loaders.py → repo root
    return Path(__file__).resolve().parents[2]


def load_yaml_config(cfg: dict[str, Any] | None, name: str) -> dict[str, Any]:
    """Load config/{name}.yaml merged under optional cfg[name] overrides."""
    root = _root_from_cfg(cfg)
    path = root / "config" / f"{name}.yaml"
    data: dict[str, Any] = {}
    if path.exists():
        with path.open(encoding="utf-8") as f:
            data = dict(yaml.safe_load(f) or {})
    override = (cfg or {}).get(name)
    if isinstance(override, dict):
        # shallow merge; nested weights handled by callers
        merged = {**data, **override}
        return merged
    return data
