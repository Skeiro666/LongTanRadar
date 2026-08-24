from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

_YAML_CACHE: dict[tuple[str, float], dict[str, Any]] = {}


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
        key = (str(path.resolve()), path.stat().st_mtime)
        cached = _YAML_CACHE.get(key)
        if cached is None:
            with path.open(encoding="utf-8") as f:
                cached = dict(yaml.safe_load(f) or {})
            _YAML_CACHE[key] = cached
            # drop stale keys for same path
            for k in list(_YAML_CACHE):
                if k[0] == key[0] and k != key:
                    _YAML_CACHE.pop(k, None)
        data = dict(cached)
    override = (cfg or {}).get(name)
    if isinstance(override, dict):
        # shallow merge; nested weights handled by callers
        merged = {**data, **override}
        return merged
    return data
